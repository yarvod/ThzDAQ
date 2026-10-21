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
- GPIB: Prologix Ethernet (`prologix`), Prologix USB (`prologix_usb`, через serial) и любой
  VISA-ресурс (`visa`, `resource="GPIB0::19::INSTR"`): адаптеры NI GPIB-USB-HS, Keysight 82357B,
  а также USBTMC/LXI. VISA — опциональная зависимость `thzdaq-instruments[visa]` (pyvisa +
  бэкенд NI-VISA или pyvisa-py). Последовательные приборы за шлюзом serial→Ethernet
  (WaveShare и т.п.) — это обычный `socket` с нужными терминаторами.
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
class Thermometer(Protocol):        read_temperature() -> K
class SpectrumAnalyzer(Protocol):   set_center_frequency/set_span/set_*_bandwidth, read_peak(), read_trace()
class NetworkAnalyzer(Protocol):    set_frequency_range(), set_points(), read_trace() -> ComplexTrace
class VacuumGauge(Protocol):        read_pressure() -> Pa
class Rotator(Protocol):            rotate_to(deg), get_angle()
class Compressor(Protocol):         turn_on/off(), read_temperatures() -> K, read_pressures() -> Pa
```
Отдельного `BiasPort` нет: SIS-канал — это `VoltageSource + VoltageCurrentMeter`, канал блока
питания — `Switchable + VoltageSource + CurrentSource + VoltageCurrentMeter`.
Единицы — СИ (К, Па) даже там, где прибор отдаёт °C, psig или гПа: пересчёт в драйвере,
обратный — только в UI. Углы — в градусах.

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

### 4.5 Station — профиль стенда ✅
Связка «роль → прибор/канал/опции» описывается один раз в YAML (`stations/*.yaml`, пример —
`stations/2sb.example.yaml`):
```yaml
instruments:
  rigol:     {driver: rigol.dp832a, connection: {kind: socket, host: 169.254.0.14, port: 5555}}
  lo_gen:    {driver: agilent.e8247c, connection: {kind: prologix, host: 169.254.156.103, gpib: 19}}
  sis_block: {driver: scontel.sis_block, connection: {...}}
  nrx:       {driver: rs.nrx, connection: {...}, options: {aperture_time: 0.05}, sim_options: {power: -30}}
roles:
  if_selector: {instrument: rigol, channel: 2, adapter: sideband_selector, options: {upper_when_on: true}}
  lo:          {instrument: lo_gen, adapter: scaled_frequency, options: {multiplier: 18}}
  sis1:        {instrument: sis_block, channel: DEV4, attributes: {offset_voltage: 3.3e-5}}
  coil1:       {instrument: sis_block, channel: DEV3, accessor: ctrl}
```
- Роль = прибор → часть (`accessor(channel)`, по умолчанию `channel`) → атрибуты (смещения) →
  адаптер порта. Адаптеры делегируют всё, что не переопределяют: LO за `scaled_frequency`
  по-прежнему умеет `set_output`/`set_power`.
- Адаптеры: `switch` (с инверсией), `scaled_frequency`, `sideband_selector`; новые — через
  `register_adapter()` без правок `Station` (OCP).
- `Station` открывает приборы лениво, роли кэшируются, один прибор делится между ролями
  (`sis1`, `sis2` на одном блоке). `station.require({...})` строит роли и проверяет возможности,
  сообщая обо всех проблемах сразу. `snapshot()` — профиль + `*IDN?` для метаданных измерения.
- `simulate=True` (или `simulate: true` у прибора) подставляет симулятор драйвера с `sim_options`.
- Импорт старого `settings.ini` (`[Configs]`, QVariant — нужен PySide6) → профиль: два «SIS-блока»
  на одном хосте сливаются в один прибор с ролями `sisN`/`sisN_ctrl`, адаптеры Prologix
  пропускаются, NRX/YIG/чоппер берутся из старых констант `state`.
- CLI: `thzdaq-station import-legacy | show | check [--simulate]`.

### 4.6 Procedure — измерение без Qt ✅
```python
@register_procedure
class IFNoise(Procedure):
    name = "if.hot_cold"
    title = "IF noise (hot/cold)"
    requires = {"detector": PowerDetector, "if_filter": TunableFilter, "load": LoadSwitch}
    plots = (PlotSpec("power", "P-IF", stream="power", x="frequency", y="power",
                      x_scale=GHZ, group_by=("load",)), ...)

    frequency = SweepParameter("IF", default=(4e9, 12e9, 201), unit="Hz",
                               display_unit="GHz", display_scale=GHZ)
    t_hot = FloatParameter("Hot load", default=300.0, minimum=0, unit="K")

    def run(self, ctx):
        detector, if_filter, load = ctx["detector"], ctx["if_filter"], ctx["load"]
        ctx.on_exit(load.to_cold)
        for state in ("cold", "hot"):
            getattr(load, f"to_{state}")()
            for f in self.frequency.values():
                ...
                ctx.record("power", frequency=f, load=state, power=p)
                ctx.progress()
```
- Параметры декларативны (PyMeasure): значения в СИ, у каждого — единица показа и масштаб
  (`display_unit="GHz"`, `display_scale=GHZ`), поэтому форма и CLI работают в ГГц/мВ, а код — в Гц/В.
  Типы: `Float`, `Int`, `Bool`, `Choice`, `FloatList`, `Sweep(start, stop, points)`.
  `describe()` отдаёт всё, что нужно для автоформы; `check()` — проверки между параметрами.
- `ctx["role"]` — порт стенда; `ctx.record(stream, **values)` — запись в набор данных, в файл и
  событие для графиков. Процедура не знает про dock-окна (DIP): UI подписывается по `PlotSpec`.
- `ctx.sleep()` просыпается сразу при отмене, `ctx.check_cancel()`, `ctx.progress()` — без `terminate()`.
- `ctx.on_exit(callback)` — восстановление состояния (LIFO), выполняется при успехе, отмене и ошибке.
- Реестр процедур: `@register_procedure`, `get_procedure(name)`, `procedures()`.
- `roles()` может зависеть от параметров: P-V с `hot_cold=True` требует ещё `load`, SRR со
  спектроанализатором — `spectrum` вместо `detector`/`if_filter`.
- Имена параметров не могут перекрывать API `Procedure` (`parameters`, `roles`, ...) — проверка
  при объявлении класса.
- Процедуры (`thzdaq list`):

  | Имя | Что делает | Роли |
  |---|---|---|
  | `sis.iv_curve` | I-V | bias |
  | `sis.pv_curve` | P-V, опционально hot/cold (Y, Tn от V) и углы сетки | bias, detector (+load, +grid) |
  | `sis.y_factor_voltage` | P-V с hot/cold по умолчанию | bias, detector, load |
  | `sis.reflection` | S-параметры VNA по развёртке смещения | bias, vna |
  | `sis.shot_noise` | Rd в двух точках, P-IF, шум ПЧ-усилителя | bias, detector, if_filter |
  | `grid.current_angle` | ток SIS от угла сетки | grid, bias |
  | `if.hot_cold` | P-IF hot/cold, Y и Tn | detector, if_filter, load |
  | `two_sb.if_balance` | P-IF обоих каналов для пар смещений | sis1, sis2, if_selector, detector, if_filter |
  | `two_sb.pump_balance` | токи накачки от частоты LO или RF | sis1, sis2, lo/test_tone (+detector) |
  | `two_sb.srr` | test tone в каждой полосе → SRR по ПЧ; опц. Y/Tn | + test_tone, detector или spectrum, load |
  | `two_sb.tn` | Y и Tn верхнего и нижнего каналов | sis1, sis2, if_selector, detector, if_filter, load |
  | `two_sb.optimization` | карты SRR и Tn по сетке SIS1×SIS2 | все роли 2SB |

### 4.7 Runner ✅
- `MeasurementRunner(station, store, observers)` (чистый Python): проверяет параметры, строит роли
  (`roles={"bias": "sis1"}` сопоставляет роли процедуры и стенда), создаёт `Dataset` со снимком стенда,
  вызывает `run(ctx)`, выполняет cleanup и пишет статус `completed | cancelled | failed`.
  Не хватает роли — ошибка до создания файла.
- `RunObserver`: `on_started / on_record / on_progress / on_log / on_finished`; упавший наблюдатель
  (например, график) не останавливает измерение. `QtRunner` в GUI будет таким наблюдателем,
  переносящим события в Qt-сигналы.
- Один раннер — одно измерение за раз; `cancel()` из другого потока.

### 4.8 Данные ✅
- `Dataset`: id, процедура, параметры (JSON), снимок стенда с `*IDN?`, время, статус, ошибка,
  потоки записей, результаты, метаданные (роли, traceback, ошибки cleanup).
- `DataStore(root)`: `<root>/<дата>/<id>_<процедура>.jsonl` — JSON Lines, строка на запись,
  flush после каждой (опционально fsync). Файл без «футера» читается как `interrupted`,
  оборванная последняя строка игнорируется. Комплексные числа и NaN/inf сохраняются без потерь.
- CLI: `thzdaq list | describe <procedure> | run <procedure> --station ... [--simulate]
  [--role bias=sis1] [--set voltage=0:7:351] | show <file>`.

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
2. **Драйверы** ✅: Rigol DP832A, R&S HMP2030 / NRX / ZVA67 / FSEK30, Keithley 2200,
   Agilent E8247C, Scontel SIS, NI YIG (HTTP), Modbus-чоппер, LakeShore 336, SRS SR830,
   Sumitomo F-70 (RS-232 и REST), Pfeiffer TC 110 и вакуумметры (RS-485), Arduino grid —
   с симуляторами, эмуляторами протоколов и контрактными тестами.
3. **Станция** ✅: пакет `thzdaq-core` — профиль стенда (YAML), роли, адаптеры портов, `Station`,
   импорт `Configs/*` из `settings.ini`, CLI `thzdaq-station`. Редактор профиля в UI — на этапе 5.
4. **Измерения** ✅: каркас (`Procedure`, параметры, `PlotSpec`, `MeasurementRunner`, `Dataset`,
   JSON Lines, CLI `thzdaq`) и все измерения старого приложения и ветки `2sb` как процедуры.
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
