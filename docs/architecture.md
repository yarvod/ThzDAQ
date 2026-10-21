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

Репозиторий — uv workspace из трёх дистрибутивов. Границы слоёв держатся зависимостями:
в `thzdaq-instruments` физически нет Qt и numpy, тест `test_package_does_not_import_gui_or_numpy`
это проверяет.

```
packages/
  thzdaq-instruments/          # import thzdaq_instruments — без Qt, можно отдать отдельно
    src/thzdaq_instruments/
      errors.py                # InstrumentError → Connection / Timeout / Response / Configuration
      units.py                 # соглашение: СИ внутри (Гц, В, А, K), мощность в дБм
      readings.py              # ChannelReading ...
      capabilities.py          # интерфейсы по возможностям (раздел 4.3)
      instrument.py            # Instrument, ScpiInstrument, Channel
      registry.py              # каталог драйверов, open() через пул
      transport/               # base.py, links.py (TCP, serial), prologix.py, pool.py, fake.py
      drivers/                 # power_supply (шаблон), rigol, rohde_schwarz, keithley, agilent,
                               # scontel, national_instruments, chopper
      sim/                     # симуляторы каждого интерфейса
  thzdaq-core/                 # import thzdaq_core — без Qt (этапы 3–4)
    src/thzdaq_core/
      station/                 # конфиги приборов, роли, порты, профили стендов (YAML)
      measurements/            # Procedure, Parameter, Context, PlotSpec, runner, procedures/
      data/                    # Dataset, автосохранение
      analysis/                # iv, noise, two_sb — чистые расчёты
      cli.py                   # thzdaq run <procedure> --station stations/2sb.yaml
app/                           # thzdaq-gui (этап 5): PySide6, pyqtgraph, QtAds
  main_window.py, qt_runner.py, forms.py, plots/, panels/, setup/
  app.py                       # composition root
```

Тесты пакета: `uv run --isolated --package thzdaq-instruments pytest packages/thzdaq-instruments`.

## 4. Ключевые абстракции

### 4.1 Transport — «физический порт»
Два уровня:
- `Link` — физическое соединение построчно (`SocketLink`, `SerialLink`), со своим `RLock`.
- `Transport` — доступ одного прибора к линку: `write`, `read`, `query`, `transaction()`.
  `MessageTransport` пишет напрямую, `PrologixTransport` перед командой выбирает GPIB-адрес
  (`++addr` только при смене) и читает через `++read eoi`.

```python
@dataclass(frozen=True)
class ConnectionSpec:
    kind: str                 # "socket" | "serial" | "prologix" | "prologix_usb"
    host: str | None = None
    port: int | None = None   # для prologix по умолчанию 1234
    serial_port: str | None = None
    gpib: int | None = None
    timeout: float = 2.0
    read_delay: float = 0.0
    read_termination: str | None = "\n"   # None — старый режим «один recv»
```
- `TransportPool.acquire(spec) -> Transport`: один линк на физическую точку (`spec.link_key`),
  подсчёт ссылок, линк закрывается последним `transport.close()`. Prologix настраивается один
  раз на линк.
- Каждый `query` держит блокировку линка от записи до чтения: генераторы и спектроанализатор за
  одним Prologix не перемешивают команды (есть тест, который без блокировки падает).
- `FakeLink` записывает команды и отвечает по сценарию — на нём тестируются драйверы.
- HTTP (YIG на NI) и Modbus (чоппер) не построчные: драйвер сам открывает клиент
  (`JsonHttpClient`, `PymodbusRegisters`) по `ConnectionSpec(kind="http" | "modbus_tcp" | "modbus_rtu")`;
  пул такие соединения не выдаёт. Клиенты подменяются в тестах (`client=`, `registers=`).

### 4.2 Instrument и Channel
```python
class Instrument:                  # база драйверов и симуляторов: имя, каналы, close()
    channel_class: type[Channel] | None = None
    channel_keys: tuple = ()
    def channel(self, key) -> Channel: ...

class ScpiInstrument(Instrument):  # текстовые команды поверх Transport
    def __init__(self, transport: Transport, *, name=None): ...
    def query_float / query_int / query_bool(...)  # мусор в ответе → InstrumentResponseError
    def identify(self) -> str: ...                 # *IDN?

class Channel:                     # часть прибора, как InstrumentChannel в QCoDeS
    def __init__(self, instrument, key): ...
```
Многоканальные приборы отдают каналы: `supply.channel(2)`, `sis_block.channel("DEV4")`.
Потребитель работает с каналом, а не с «прибором + номером».

### 4.3 Capabilities — маленькие интерфейсы (ISP)
Интерфейс описывает одну возможность; прибор/канал реализует несколько. Это `Protocol` только из
методов, поэтому реестр выводит возможности драйвера из класса (`issubclass`), без ручных списков.
```python
class Identifiable(Protocol):       def identify(self) -> str
class Switchable(Protocol):         set_output(bool), get_output() -> bool
class VoltageSource(Protocol):      set_voltage(V), get_voltage() -> V   # уставка
class CurrentSource(Protocol):      set_current(A), get_current() -> A   # уставка/предел
class VoltageCurrentMeter(Protocol): measure() -> ChannelReading         # факт
class FrequencySource(Protocol):    set_frequency(Hz), get_frequency() -> Hz
class PowerLevel(Protocol):         set_power(dBm), get_power() -> dBm
class PowerDetector(Protocol):      read_power() -> dBm                  # ошибка — исключение
class TunableFilter(Protocol):      tune(Hz) -> Hz                       # реально выставленная
class LoadSwitch(Protocol):         to_hot(), to_cold()
```
Отдельного `BiasPort` нет: SIS-канал — это `VoltageSource + VoltageCurrentMeter`, канал блока
питания — `Switchable + VoltageSource + CurrentSource + VoltageCurrentMeter`.
Позже добавятся `SpectrumAnalyzer`, `NetworkAnalyzer`, `Thermometer`, `Rotator`, `Compressor`,
`VacuumGauge` — по мере переноса приборов.

Блоки питания реализуют канал один раз (`SupplyChannel`), вендор задаёт только SCPI-примитивы
(`_set_output`, `_set_voltage`, `_measure`, ...) — шаблонный метод вместо трёх копий.
У каждого драйвера есть `connection(...)` с рекомендуемыми настройками связи (порт, терминатор,
задержка), например SIS-блок читает ответы кусками с паузой 50 мс, как старый адаптер.

Для каждой возможности есть контрактный тест (`tests/contracts.py`): симуляторы и драйверы
(на `FakeLink`) проходят одни и те же проверки — так держится LSP.

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
    requires = {"sis1": (VoltageSource, VoltageCurrentMeter),
                "sis2": (VoltageSource, VoltageCurrentMeter), "if_selector": IfSelector,
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

1. **Каркас** ✅: uv workspace, пакет `thzdaq-instruments` (errors, units, readings, capabilities,
   transport с пулом и блокировками, `Instrument/Channel`, реестр, симуляторы). Тесты.
2. **Драйверы** (первая партия ✅): Rigol DP832A, R&S HMP2030, Keithley 2200, Agilent E8247C,
   R&S NRX, Scontel SIS, NI YIG (HTTP), Modbus-чоппер — с симуляторами и контрактными тестами на
   эмуляторах SCPI. Дальше: VNA, спектроанализатор, LakeShore, Sumitomo, Pfeiffer, grid, lock-in.
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
