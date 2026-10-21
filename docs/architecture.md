# ThzDAQ: целевая архитектура (ветка `arch-refactor`)

Документ — план переписывания приложения. Цель: прибор, стенд, измерение, данные и UI
развязаны так, что новый прибор или новое измерение добавляется одним модулем, без правки
остального кода, и всё, кроме UI, тестируется без железа.

## 1. Что сейчас мешает

Замеры по `master`:

| Проблема | Где видно | Принцип |
|---|---|---|
| Глобальное изменяемое состояние | 24 файла импортируют `store.state.state` (IP, флаги потоков, константы вперемешку) | DIP |
| Слои зависят по кругу | `api/` (драйверы) импортирует `store/` (6 файлов), `store/` ссылается на `interface.*` строками (10 мест), UI находит окна через `Dock.ex` (17 мест) | DIP, SRP |
| Нет интерфейсов по типу прибора | Rigol `set_output(ch, v)`, R&S `set_output_state(ch, v)`, Keithley `set_output_state(v)`; почти одинаковые виджеты Rigol/R&S (~990 строк) | LSP, ISP, OCP |
| Логика измерений внутри виджетов | 48 классов потоков в UI-модулях, вызовы приборов прямо в `run()` | SRP |
| Небезопасная остановка | 5 вызовов `terminate()`, 68 ручных `finished.emit()` (Qt шлёт `finished` сам — слоты срабатывают дважды) | — |
| Общий транспорт без блокировок | Prologix — синглтон для генераторов и спектроанализатора, монитор и измерение могут перемешать команды на шине GPIB | — |
| Ошибки теряются | `DeviceConnectionError(BaseException)` не ловится `except Exception`; `@exception` возвращает `None` | — |
| Данные не сохраняются по ходу | Измерение живёт в памяти до ручного сохранения или dump при выходе | — |
| Часть приборов вне конфигов | NRX, YIG, chopper берутся из `state` по IP | OCP |

## 2. На что опираемся

Готового «novasoft» найти не удалось. Близкие по задаче открытые фреймворки, идеи из которых берём
(не зависимость, а образец):

- **QCoDeS** (Microsoft / QuTech Delft) — драйвер = соединение + дерево `InstrumentChannel` с
  `Parameter` (имя, единицы, пределы, get/set). Берём: каналы как объекты, параметры с единицами.
- **Bluesky + ophyd** (NSLS-II) — единый интерфейс устройств (`read()`, `set()`), эксперимент как
  план, исполняемый RunEngine, данные как поток документов с метаданными. Берём: процедура отдельно от
  исполнителя, поток записей с метаданными, «цифровой двойник» (симулятор) вместо железа.
- **NOMAD CAMELS** (FAU) — GUI поверх bluesky: менеджер приборов, протоколы измерений, ручное
  управление, самоописывающие данные (HDF5/NeXus). Берём: разделение «приборы / протоколы / ручное
  управление», полные метаданные в файле.
- **PyMeasure** — `Procedure` с типизированными `Parameter`, из которых автоматически строится форма
  в GUI; `Worker` исполняет, `Results` пишутся по ходу. Берём: декларативные параметры → автоформа.

Сам bluesky/QCoDeS не тянем: для одного стенда с ~15 приборами это лишний вес; нам нужен тонкий
собственный каркас с теми же идеями.

## 3. Слои

```
ui  ──►  application  ──►  domain  ◄──  hardware (drivers)  ──►  transport
 │            ▲                                   ▲
 └──── app (composition root: собирает всё, внедряет зависимости) ────┘
```

Правило: стрелки только вниз/внутрь. `domain` не импортирует ничего из проекта и не знает про Qt.
Драйверы не знают про Qt, UI и конфиги. UI не создаёт драйверы сам — получает сервисы.

```
thzdaq/
  domain/
    units.py           # соглашение: СИ внутри (Гц, В, А, K), мощность в дБм
    errors.py          # InstrumentError → ConnectionError / TimeoutError / ResponseError
    capabilities.py    # интерфейсы по возможностям (раздел 4)
    readings.py        # ChannelReading, PowerReading, Trace ...
    analysis/          # iv.py, noise.py, two_sb.py — чистые расчёты
  hardware/
    transport/         # base.py, socket.py, prologix.py, serial.py, http.py, pool.py
    instrument.py      # Instrument, Channel — базовые классы
    drivers/           # rigol/dp832a.py, rohde_schwarz/hmp2030.py, scontel/sis_block.py, ...
    sim/               # симуляторы каждого интерфейса
    registry.py        # каталог драйверов
  station/
    config.py          # InstrumentConfig, RoleSpec, StationConfig (dataclass'ы)
    ports.py           # ChannelSwitch, ScaledFrequencySource, IfSelector ...
    station.py         # Station: роли → готовые порты
    storage.py         # YAML/JSON профили стендов
  measurements/
    base.py            # Procedure, Parameter, Context, PlotSpec
    runner.py          # исполнитель без Qt: отмена, прогресс, запись данных
    procedures/        # iv_curve.py, pv_curve.py, y_factor.py, two_sb/*.py ...
  data/
    dataset.py         # Dataset: метаданные + записи
    store.py           # автосохранение по ходу (JSON lines / HDF5)
  ui/
    main_window.py     # окно, docks, перспективы
    qt_runner.py       # QThread-обёртка над runner → сигналы
    forms.py           # форма из Parameter'ов процедуры
    plots/             # PlotPanel по PlotSpec
    panels/            # ручное управление по capability: PowerSupplyPanel, SignalSourcePanel ...
    setup/             # редактор приборов и профиля стенда
  app.py               # composition root
main.py                # точка входа: from thzdaq.app import run
```

## 4. Ключевые абстракции

### 4.1 Transport — «физический порт»
```python
class Transport(Protocol):
    def write(self, command: str) -> None: ...
    def query(self, command: str) -> str: ...
    def close(self) -> None: ...

@dataclass(frozen=True)
class ConnectionSpec:
    kind: str            # "socket" | "prologix" | "serial" | "http" | "visa"
    host: str | None = None
    port: int | None = None
    gpib: int | None = None
    timeout: float = 2.0
```
- `TransportPool.acquire(spec) -> Transport`: одно физическое соединение на конечную точку
  (Prologix-хост, сокет), подсчёт ссылок, закрывается последним пользователем.
- Блокировка на физическую шину: `query` атомарен, GPIB-адрес выбирается под той же блокировкой.
- Драйвер получает готовый `Transport` в конструкторе (DIP) — в тестах подставляется фейк.

### 4.2 Instrument и Channel
```python
class Instrument(ABC):
    def __init__(self, transport: Transport): ...
    def identify(self) -> str: ...
    def close(self) -> None: ...

class Channel:                     # часть прибора, как InstrumentChannel в QCoDeS
    def __init__(self, parent: Instrument, index: int): ...
```
Многоканальные приборы отдают каналы: `supply.channel(2)`, `sis_block.bias("DEV4")`.
Потребитель работает с каналом, а не с «прибором + номером».

### 4.3 Capabilities — маленькие интерфейсы (ISP)
Интерфейс описывает одну возможность; прибор/канал реализует несколько.
```python
class Switchable(Protocol):        # выход вкл/выкл
    def set_output(self, value: bool) -> None: ...
    def get_output(self) -> bool: ...

class VoltageSource(Protocol):
    def set_voltage(self, volts: float) -> None: ...

class VoltageCurrentMeter(Protocol):
    def measure(self) -> ChannelReading: ...

class FrequencySource(Protocol):   # Гц на выходе, с учётом множителя
    def set_frequency(self, hz: float) -> None: ...

class PowerLevel(Protocol):
    def set_power(self, dbm: float) -> None: ...

class PowerDetector(Protocol):
    def read_power(self) -> float: ...           # дБм, бросает InstrumentError

class TunableFilter(Protocol):
    def set_frequency(self, hz: float) -> float: ...

class LoadSwitch(Protocol):
    def hot(self) -> None: ...
    def cold(self) -> None: ...

class BiasPort(Protocol):          # один SIS-канал
    def set_voltage(self, volts: float) -> None: ...
    def read(self) -> ChannelReading: ...
```
Плюс `SpectrumAnalyzer`, `NetworkAnalyzer`, `Thermometer`, `Rotator` (grid), `Compressor`,
`VacuumGauge` — по мере переноса приборов.

Пример: канал Rigol, канал R&S и Keithley все реализуют `Switchable + VoltageSource +
VoltageCurrentMeter`. Различия в SCPI спрятаны в драйвере (LSP: подменяемы без `if vendor`).

### 4.4 Ports — логические порты поверх каналов
Измерению нужна роль, а не конкретный прибор. Порты — маленькие адаптеры (Decorator/Adapter):
```python
@dataclass
class ChannelSwitch:               # Switchable из любого Switchable с инверсией
    target: Switchable
    inverted: bool = False
    def set(self, value: bool): self.target.set_output(value != self.inverted)

@dataclass
class ScaledFrequencySource:       # LO ×18: снаружи частота на смесителе
    source: FrequencySource
    multiplier: float
    def set_frequency(self, hz): self.source.set_frequency(hz / self.multiplier)

class IfSelector:                  # выбор боковой полосы IF через любой Switch
    def __init__(self, switch: ChannelSwitch): ...
    def select(self, side_band: str): self.switch.set(side_band == "upper")
```
Завтра IF переключает реле на Arduino — пишется ещё один `Switchable`, процедуры не меняются (OCP).

### 4.5 Station — профиль стенда
Связка «роль → прибор/канал/опции» описывается один раз и хранится в файле (`stations/2sb.yaml`):
```yaml
instruments:
  rigol: {driver: rigol.dp832a, connection: {kind: socket, host: 169.254.0.14, port: 5555}}
  lo_gen: {driver: agilent.e8247c, connection: {kind: prologix, host: 169.254.156.103, gpib: 19}}
roles:
  if_switch: {instrument: rigol, channel: 2, inverted: false}
  lo:        {instrument: lo_gen, multiplier: 18}
  sis1:      {instrument: sis_block, channel: DEV4, offset_voltage: 0.033e-3}
```
`Station` собирает из конфигурации готовые порты и отдаёт их по ролям. Процедура объявляет, какие
роли и каких типов ей нужны — проверка до старта, а не посреди измерения.

### 4.6 Procedure — измерение без Qt
```python
class TnProcedure(Procedure):
    title = "2SB Tn"
    requires = {"sis1": BiasPort, "sis2": BiasPort, "if_selector": IfSelector,
                "detector": PowerDetector, "yig": TunableFilter, "load": LoadSwitch}
    lo_frequency = FloatParameter("LO frequency", unit="GHz", default=263)
    if_sweep = SweepParameter("IF", unit="GHz", default=(4, 12, 201))
    plots = [PlotSpec("P-IF", x="if", y="power", group_by=("side_band", "load"))]

    def run(self, ctx: Context):
        for side_band in ("upper", "lower"):
            ctx.station.if_selector.select(side_band)
            for load in ("cold", "hot"):
                ...
                ctx.record(if_=f, power=p, side_band=side_band, load=load)
                ctx.check_cancel()
```
- Параметры декларативны (PyMeasure): из них строится форма, валидация, сохранение в метаданные.
- `ctx.record()` — запись в набор данных и одновременно событие для графиков. Процедура не знает про
  dock-окна (DIP): UI подписывается по `PlotSpec`.
- `ctx.check_cancel()`, `ctx.sleep()`, `ctx.progress()` — отмена без `terminate()`.
- Восстановление состояния — через `ctx.on_exit(...)` или `try/finally` в процедуре.

### 4.7 Runner
- `MeasurementRunner` (чистый Python): открывает станцию, создаёт `Dataset`, вызывает
  `procedure.run(ctx)`, гарантирует закрытие и запись ошибки в данные.
- `QtRunner` в `ui/` — тонкая обёртка: QThread + сигналы `progress`, `record`, `error`, `finished`.
- Очередь измерений и запрет параллельного доступа к одним ролям (аренда ресурсов).

### 4.8 Данные
- `Dataset`: метаданные (процедура, параметры, снимок станции, `*IDN?` приборов, версия, время) +
  записи. Пишется на диск по ходу (JSON lines или HDF5) — краш не теряет данные.
- Таблица Data в UI становится каталогом файлов + открытые в сессии наборы.

### 4.9 Мониторинг и ручное управление
- `PollingService`: один планировщик опроса на прибор вместо отдельного потока в каждом виджете
  (сейчас 48 классов потоков). Виджеты подписываются на показания.
- Панели ручного управления по capability: `PowerSupplyPanel` для любого блока питания,
  `SignalSourcePanel` для любого генератора. Специфичное для драйвера — опциональная вкладка.

### 4.10 Реестр драйверов и симуляторы
```python
registry.register("rigol.dp832a", RigolDP832A, config=PowerSupplyOptions, sim=SimPowerSupply)
```
- Один `InstrumentManager` вместо 10 менеджеров в `store/__init__.py`.
- `DeviceComboBox(capability=Switchable)` показывает все подходящие каналы любых вендоров.
- `main.py --sim stations/2sb.yaml` запускает всё приложение на симуляторах: разработка на маке,
  демо, тесты процедур целиком.

### 4.11 Конфигурация приложения
- Глобальный `state` заменяется типизированным `AppSettings` (dataclass) + профили стендов.
- `settings.ini` остаётся только для геометрии окон и перспектив QtAds.

## 5. SOLID — как выполняется

| Принцип | Решение |
|---|---|
| SRP | Драйвер — только протокол прибора; Procedure — только логика измерения; Runner — исполнение; Dataset — хранение; виджет — отображение |
| OCP | Новый прибор = драйвер + регистрация; новое измерение = файл Procedure; ядро не правится |
| LSP | Все реализации capability взаимозаменяемы (контрактные тесты одной пачкой для всех драйверов и симулятора) |
| ISP | Мелкие capability вместо «толстого» класса прибора; процедура зависит только от нужных ролей |
| DIP | Процедуры и UI зависят от интерфейсов; конкретику внедряет `app.py` (composition root) |

## 6. Тестирование
- `domain/analysis` — обычные юнит-тесты.
- Драйверы — тесты на фейковом `Transport` (проверяем SCPI-строки и разбор ответов).
- Контрактные тесты capability: один набор тестов прогоняется на каждом драйвере-фейке и симуляторе.
- Процедуры — целиком на симуляторной станции.
- UI — smoke-тест offscreen: окно собирается, формы строятся из параметров.

## 7. План перехода (в этой ветке, приложение рабочее после каждого этапа)

1. **Каркас**: пакет `thzdaq/`, `domain` (units, errors, capabilities, readings), `transport` с
   пулом и блокировками, `Instrument/Channel`, реестр, симуляторы. Тесты.
2. **Драйверы**: перенос по одному в `hardware/drivers` с реализацией capability
   (сначала блоки питания, генераторы, NRX, SIS, YIG, chopper). Старый `api/` временно реэкспортирует.
3. **Станция**: конфиги приборов + профиль стенда (YAML), редактор в UI, импорт текущих
   `Configs/*` из `settings.ini`.
4. **Измерения**: `Procedure`/`Runner`/`Dataset`/автоформы/`PlotSpec`; перенос I-V, P-V, Y-factor,
   VNA, shot noise, затем 2SB из ветки `2sb`.
5. **UI**: новая главная форма, панели по capability, `PollingService`, каталог данных.
6. **Удаление старого**: `api/`, `store/`, `interface/`, `threads/`, глобального `state`.
7. Мерж в `master`.

Принцип переноса — strangler: новое пишется рядом, старое удаляется по мере замены, а не
«большим взрывом» в конце.

## 8. Чего не делаем
- Не тянем bluesky/QCoDeS/EPICS целиком — берём идеи.
- Не вводим библиотеку единиц (pint) — соглашение «СИ внутри, пересчёт на границе UI».
- Не делаем DI-фреймворк и плагины через entry points — хватает реестра и `app.py`.
- Не переходим на asyncio — опрос и измерения в потоках с блокировками транспорта.

## Ссылки
- QCoDeS, создание драйверов: https://microsoft.github.io/Qcodes/examples/writing_drivers/Creating-Instrument-Drivers.html
- Bluesky / ophyd, устройства из сигналов: https://nbviewer.org/github/bluesky/tutorials/blob/main/Ophyd/01%20-%20Group%20Signals%20into%20Devices.ipynb
- NOMAD CAMELS: https://arxiv.org/abs/2402.07548
- PyMeasure, GUI из Procedure: https://pymeasure.readthedocs.io/en/latest/tutorial/graphical.html
