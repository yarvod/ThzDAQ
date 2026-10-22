# ThzDAQ: целевая архитектура (ветка `arch-refactor`)

Документ — план переписывания приложения. Цель: прибор, стенд, измерение, данные и UI
развязаны так, что новый прибор или новое измерение добавляется одним модулем, без правки
остального кода, и всё, кроме UI, тестируется без железа.

## 1. Что мешало в старом приложении

Замеры по `master` до рефакторинга (код удалён на этапе 6):

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
      data/                    # Measurement, Table, Column; JSON-стор
      analysis/                # iv, noise, two_sb — чистые расчёты
      cli.py                   # thzdaq run <procedure> --station stations/2sb.yaml
app/                           # thzdaq-gui (этап 5): PySide6, pyqtgraph, QtAds
  main_window.py, theme.py, graphs.py, forms.py, docks/ (setup, devices, measure, data, log)
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

### 4.4 Величины и подустройства
- **Величина** (`thzdaq_instruments.quantities.Quantity`): то, что часть прибора читает или
  задаёт, — ключ, название, единица СИ (или dBm/deg), get/set. Величины выводятся из
  возможностей: `VoltageSource` → «Voltage setpoint, V», `VoltageCurrentMeter` → «Voltage»,
  «Current» (один вызов `measure()` на оба), `PowerDetector` → «Power, dBm» и т. д.; драйвер
  добавляет свои через `quantities` (закоротка SIS — `SHORT`). Из величин строятся элементы
  управления и мониторинг в доках, поэтому новый драйвер сразу получает рабочий док.
- **Каналы** (`channel_keys`) — физические одинаковые выходы, заданные моделью: CH1–CH3 блока
  питания, входы LakeShore, каналы YIG. Показываются внутри дока своего прибора.
- **Подустройства** (`Instrument.subdevices: {kind: SubdeviceType}`) — функциональные устройства,
  которые пользователь добавляет к прибору: на SIS-блоке `sis_bias` (DEV1–DEV4, `channel()`) и
  `sis_coil` (`ctrl()`). У каждого своё имя, настройки и док; на одном DEV может быть несколько
  конфигов (разные смесители с разными смещениями и калибровками) — `AttributePort` применяет
  настройки своего конфига перед каждым вызовом.
- **Адаптеры** поверх прибора или канала — тоже виды устройств: `frequency_multiplier` (LO ×18),
  `sideband_selector` (переключатель IF на канале блока питания), `switch` (с инверсией).
  Делегируют всё, что не переопределяют: LO за умножителем умеет `set_output`/`set_power`.
- Виды и их настройки — `thzdaq_core.station.kinds`: у каждого вида настройки описаны
  параметрами с единицами (как у процедур), из них строится форма в Setup.

### 4.5 Station — профиль стенда ✅
Профиль (`stations/*.yaml`, версия 2) — приборы и устройства на них. Id называет тип прибора
(`power_supply_3`, `power_meter_1`), вендор и модель — в `driver` и `title`:
```yaml
version: 2
instruments:
  sis_block_1:
    driver: scontel.sis_block
    title: Scontel SIS block 1
    connection: {kind: socket, host: 169.254.190.83, port: 9876, read_delay: 0.05, read_termination: null}
    devices:
      sis_bias_1: {kind: sis_bias, channel: DEV4, title: SIS b1d4, settings: {offset_voltage: 3.3e-05}}
      sis_coil_1: {kind: sis_coil, channel: DEV3, title: SIS b1d4 coil}
  signal_generator_1:
    driver: agilent.e8247c
    connection: {kind: prologix, host: 169.254.156.103, gpib: 19}
    devices:
      lo_1: {kind: frequency_multiplier, title: LO x18, settings: {multiplier: 18}}
  power_supply_1:
    driver: rigol.dp832a
    connection: {kind: socket, host: 169.254.0.14, port: 5555}
    devices:
      if_switch_1: {kind: sideband_selector, channel: 2, settings: {upper_when_on: true}}
  power_meter_1: {driver: rs.nrx, connection: {...}, options: {aperture_time: 0.05}}
```
- Ссылки на устройства: сам прибор (`power_meter_1`), канал (`power_supply_1:2`) или
  настроенное устройство (`sis_bias_1`; id уникальны в станции).
- `Station.devices()` — список `DeviceInfo` (ссылка, название, вид, возможности) без открытия
  приборов: по нему строятся меню, доки и списки выбора в измерениях. `quantities(ref)` — величины.
- Приборы открываются лениво, устройства кэшируются. `require(devices, requirements)` строит
  устройства для слотов измерения и проверяет возможности, сообщая обо всех проблемах сразу.
  `reconfigure(config)` принимает изменённый профиль и переоткрывает только приборы с новой связью.
  `snapshot()` и `device_use(ref)` — метаданные для измерения.
- `simulate=True` (или `simulate: true` у прибора) подставляет симулятор с `sim_options`.
- Профили версии 1 (роли) читаются и переводятся в устройства автоматически.
- Импорт старого `settings.ini` (`[Configs]`, QVariant — нужен PySide6): SIS-конфиги одного
  хоста сливаются в один блок с устройствами `sis_bias_N`/`sis_coil_N`, названия из старых
  конфигов становятся `title`; адаптеры Prologix пропускаются; NRX/YIG/чоппер — из констант `state`.
- CLI: `thzdaq-station import-legacy | show | check [--simulate] [--devices ...]`.

### 4.6 Procedure — измерение без Qt ✅
```python
@register_procedure
class IFNoise(Procedure):
    name = "if.hot_cold"
    title = "IF noise (hot/cold)"
    requires = {"detector": PowerDetector, "if_filter": TunableFilter, "load": LoadSwitch}
    plots = (PlotSpec("power", "P-IF", table="power", x="frequency", y="power",
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
- Процедура объявляет **слоты** устройств (`requires`, `slots()`) с нужными возможностями;
  какое устройство стенда играет слот, выбирает пользователь (комбобоксы в доке измерения,
  `--device bias=sis_bias_1` в CLI). `slot_kinds` подсказывает вид: слот `bias` показывает
  SIS bias, а не каждый канал блока питания.
- Параметры декларативны (PyMeasure): значения в СИ, у каждого — единица показа и масштаб.
  Типы: `Float`, `Int`, `Bool`, `Choice`, `FloatList`, `Sweep(start, stop, points)`.
- `ctx["slot"]` — устройство; `ctx.record(table, **values)` — строка таблицы измерения и событие
  для графиков. Процедура не знает про доки (DIP): GUI подписывается по `PlotSpec`.
- `ctx.sleep()` просыпается сразу при отмене; `ctx.on_exit(callback)` — восстановление (LIFO).
- `slots()` может зависеть от параметров: P-V с `hot_cold=True` требует ещё `load`.
- Процедуры (`thzdaq list`):

  | Имя | Что делает | Слоты |
  |---|---|---|
  | `sis.iv_curve` | I-V | bias |
  | `sis.cl_curve` | ток SIS от тока катушки (I-CL) | coil, bias |
  | `sis.demagnetize` | размагничивание | coil |
  | `sis.pv_curve` | P-V, опционально hot/cold (Y, Tn от V) и углы сетки | bias, detector (+load, +grid) |
  | `sis.y_factor_voltage` | P-V с hot/cold по умолчанию | bias, detector, load |
  | `sis.reflection` | S-параметры VNA по развёртке смещения | bias, vna |
  | `sis.shot_noise` | Rd в двух точках, P-IF, шум ПЧ-усилителя | bias, detector, if_filter |
  | `grid.current_angle` | ток SIS от угла сетки | grid, bias |
  | `if.hot_cold` | P-IF hot/cold, Y и Tn | detector, if_filter, load |
  | `monitor.time` | P/T/V/I/давление выбранных устройств во времени | любые |
  | `two_sb.if_balance` | P-IF обоих каналов для пар смещений | sis1, sis2, if_selector, detector, if_filter |
  | `two_sb.pump_balance` | токи накачки от частоты LO или RF | sis1, sis2, lo/test_tone (+detector) |
  | `two_sb.srr` | test tone в каждой полосе → SRR по ПЧ; опц. Y/Tn | + test_tone, detector или spectrum, load |
  | `two_sb.tn` | Y и Tn верхнего и нижнего каналов | sis1, sis2, if_selector, detector, if_filter, load |
  | `two_sb.optimization` | карты SRR и Tn по сетке SIS1×SIS2 | все слоты 2SB |

### 4.7 Runner ✅
- `MeasurementRunner(station, store, observers)` (чистый Python): проверяет параметры, строит
  устройства слотов (`devices={"bias": "sis_bias_1"}`), создаёт `Measurement` со снимком стенда и
  описанием использованных устройств, вызывает `run(ctx)`, выполняет cleanup и пишет статус
  `completed | cancelled | failed`. Нет устройства — ошибка до создания файла.
- Автосохранение: при старте, раз в несколько секунд по мере записей и в конце.
- `RunObserver`: `on_started / on_record / on_progress / on_log / on_finished`; упавший наблюдатель
  не останавливает измерение. В GUI у каждого дока измерения свой `QtRunner`, поэтому измерения
  идут параллельно (общие приборы защищены блокировками транспорта).

### 4.8 Данные ✅
- DTO `thzdaq_core.data.measurement`: `Measurement` (id, процедура, статус, время, комментарий,
  параметры, `devices: {слот: DeviceUse}`, `tables`, результаты, снимок стенда, метаданные);
  `Table` хранит данные по колонкам словарём, как старый стор (`{"voltage": [...], ...}`), и
  описание колонок `Column(key, title, unit)` — графики и экспорт знают, что и в каких единицах.
  Названия и единицы обычных ключей — `KNOWN_COLUMNS`, процедура может уточнить `columns`.
- `MeasurementStore(root)`: `<root>/<дата>/<id>_<процедура>.json` — один JSON на измерение,
  запись через временный файл (сбой оставляет предыдущую полную версию). Файл со статусом
  `running` читается как `interrupted`. Комплексные числа и NaN/inf сохраняются без потерь.
  `export_csv()` — таблица в CSV с заголовками «Voltage, V».
- CLI: `thzdaq list | describe <procedure> | run <procedure> --station ... [--simulate]
  [--device bias=sis_bias_1] [--set voltage=0:7:351] | show <file>`.

### 4.9 GUI (`thzdaq-gui`) ✅
Интерфейс старого приложения на Qt Advanced Docking System (PySide6-QtAds): каждая часть —
док, который можно поставить куда угодно, отцепить, свернуть в боковую панель.
- Меню **Base** (Setup, Data, Event log), **Devices** (док на каждый прибор и настроенное
  устройство), **Measures** (док на каждую процедуру), **Graphs** (окно на каждый вид кривой:
  I-V, P-V, Y-V, Tn-V, P-IF, P-t, ... и свои через «New graph…»), **Help** (обновления).
- **Перспективы** — именованные раскладки доков (Create / Update / Delete / Restore defaults
  в тулбаре); хранятся с раскладкой окна в `settings.ini` рядом с программой.
- **Setup** — профиль стенда: карточки приборов (драйвер, связь, статус, Connect / Edit /
  Delete / Add device) и устройства на них; формы добавления прибора (связь по виду адаптера,
  «Recommended connection») и устройства (вид, канал, имя, настройки). Изменения сразу
  сохраняются в YAML, доки устройств появляются и исчезают вместе с ними.
- **Доки устройств** строятся из величин: значение, поле с СИ-префиксами и Set, On/Off, Read,
  Monitor с интервалом, Plot (мониторинг в графики P-t, V-t, I-t, ...). Дополнительно: SIS bias —
  смещения, калибровка (редактор с выражениями, запись в EEPROM), I-V скан; катушка — I-CL скан и
  размагничивание; чоппер — Hot/Cold; компрессор; спектроанализатор и VNA — трасса.
- **Доки измерений**: устройства по слотам (только подходящие), параметры (последние значения
  запоминаются), комментарий, Start/Stop, прогресс, лог. Записи идут в окна графиков по
  `PlotSpec`; каждый запуск — свои кривые «#N устройство группа».
- **Графики**: кривые из любых измерений; «Add curve» — измерение, таблица, колонки x/y с
  единицами; Remove hidden / all; анализ I-V (Rn, Rj, Q, щель) на I-V.
- **Data** — таблица измерений сессии и открытых файлов: комментарий редактируется и сразу
  сохраняется в файл; Plot, Save as JSON, CSV, Details, папка данных.
- Тёмная тема с оранжевым акцентом (`theme.py`: палитра Fusion, стили доков по
  `focus_highlighting_dark.css` ADS, иконки Material Design через qtawesome).
- Потоки: `DeviceWorker` — один поток для ручных обращений к приборам и опроса; `QtRunner` на
  каждый док измерения. Результаты приходят Qt-сигналами в GUI-поток.
- Обновления (Help → Check for updates): `updates.py` читает GitHub Releases (теги `vX.Y.Z`,
  архив `ThzDAQ_Windows_x64_<тег>.zip`), скачивает и распаковывает сборку; `updater.py`
  (только stdlib, собирается в `updater.exe`) ждёт выхода программы, заменяет файлы с резервом
  и откатом, сохраняет отредактированные профили `stations/` и запускает новую версию.
  Релиз: `release.py` → тег → `.github/workflows/release.yml` (тесты, `build.bat`, smoke, релиз).
- Запуск: `thzdaq-gui --station stations/2sb.example.yaml --simulate`.

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
| SRP | Драйвер — только протокол прибора; Procedure — только логика измерения; Runner — исполнение; Measurement/Store — хранение; виджет — отображение |
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
4. **Измерения** ✅: каркас (`Procedure`, параметры, `PlotSpec`, `MeasurementRunner`, `Measurement`,
   JSON Lines, CLI `thzdaq`) и все измерения старого приложения и ветки `2sb` как процедуры.
5. **UI**: первая версия ✅ (`thzdaq-gui`: стенд, измерения с автоформами, графики по PlotSpec,
   данные, ручное управление по возможностям). Дальше — функции старого окна из раздела 4.9.
6. **Удаление старого** ✅: `api/`, `store/`, `interface/`, `threads/`, `utils/`, `measures/`,
   `settings*.py/.ini` удалены; настройки приборов перенесены в `stations/lab.yaml`;
   `main.py` запускает `thzdaq-gui`; корневой проект — workspace, `uv sync` и `uv run pytest`
   работают из корня; сборка PyInstaller (`build.sh`, `build.bat`) проверена.
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
