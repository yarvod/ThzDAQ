# ThzDAQ: архитектура

Как устроено приложение. Цель переписывания: прибор, стенд, измерение, данные и интерфейс
развязаны так, что новый прибор или новое измерение добавляется одним модулем без правки
остального кода, а всё, кроме интерфейса, тестируется без железа. Приборы держит демон, а
окно, командная строка, агенты и скрипты — его клиенты (4.12; замысел и вехи —
`docs/daemon.md`).

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

Организацию интерфейса старого приложения сохранили: доки Qt Advanced Docking System,
док Setup со списком приборов, отдельный док на прибор и на измерение, окна графиков по
типу кривой (перспективы старого приложения потом убрали: ими не пользовались). Переписано то, что под ними.

## 2. На что опираемся

Близкие по задаче открытые фреймворки, идеи из которых взяты (как образец, не зависимость):

- **QCoDeS** (Microsoft / QuTech Delft) — драйвер = соединение + каналы с `Parameter` (имя,
  единицы, get/set). Взято: каналы как объекты, величины с единицами.
- **Bluesky + ophyd** (NSLS-II) — единый интерфейс устройств, эксперимент как план, исполняемый
  RunEngine, данные с метаданными. Взято: процедура отдельно от исполнителя, симулятор вместо железа.
- **NOMAD CAMELS** (FAU) — менеджер приборов, протоколы измерений, ручное управление,
  самоописывающие данные. Взято: разделение «приборы / измерения / ручное управление», полные
  метаданные в файле.
- **PyMeasure** — `Procedure` с типизированными параметрами, из которых строится форма.
  Взято: декларативные параметры → автоформа.

Сами bluesky/QCoDeS не используются: для одного стенда с ~20 приборами это лишний вес.

## 3. Пакеты и зависимости

uv workspace из восьми пакетов; зависимости только в одну сторону, и их держит сборка:
контракты import-linter в корневом `pyproject.toml` идут в pre-commit и CI.

```
thzdaq-gui ─┐
thzdaq-cli ─┼──►  thzdaq-api  ◄──  thzdaq-core  ──►  thzdaq-instruments
thzdaq-mcp ─┘         ▲                ▲   └──────►  thzdaq-analysis
                      └─ thzdaq-daemon ┘
```

- `thzdaq-instruments` — драйверы, транспорт, симуляторы (pyserial, requests, pymodbus;
  pyvisa — extra `[visa]`); ничего выше себя не знает.
- `thzdaq-analysis` — чистые расчёты (I-V, шум, 2SB), только numpy.
- `thzdaq-core` — домен, юзкейсы и адаптеры; не знает ни демона, ни клиентов.
- `thzdaq-api` — контракт демона (операции, DTO, события, ошибки, каталог, формат файла
  измерения) и его клиенты: `RemoteLab`, файлы демона и `connect_or_start()`, клиент
  скриптов `connect()`, инструменты агентов; зависит только от `msgspec`.
- `thzdaq-daemon` — процесс, который держит приборы (4.12).
- `thzdaq-gui`, `thzdaq-cli` (`thzdaq`), `thzdaq-mcp` (`thzdaq mcp`) — клиенты: импортируют
  только `thzdaq_api` и друг друга не знают. `thzdaq` — мета-пакет PyPI с extras.
- Qt — только в GUI; поэтому драйверы, станция и измерения работают в демоне, CLI, скриптах
  и тестах без интерфейса. Только корневой `main.py` знает и GUI, и демон.

```
packages/
  thzdaq-instruments/src/thzdaq_instruments/
    errors.py            # InstrumentError → Connection / Timeout / Response / Configuration
    units.py             # СИ внутри (Гц, В, А, K, Па, с), мощность в дБм, углы в градусах
    readings.py          # ChannelReading, Trace, ComplexTrace
    capabilities.py      # интерфейсы по возможностям (4.3)
    quantities.py        # величины частей прибора (4.4)
    instrument.py        # Instrument, ScpiInstrument, Channel, SubdeviceType
    registry.py          # каталог драйверов, open() через пул
    transport/           # base (ConnectionSpec, Link, Transport), links (TCP, serial, VISA),
                         # prologix, pool, http, modbus, fake
    drivers/             # power_supply (шаблон), rigol, rohde_schwarz/, keithley, agilent,
                         # scontel, national_instruments, chopper, lakeshore, srs, sumitomo,
                         # arduino (pfeiffer — отключён до переписывания)
    sim/                 # симуляторы каждого вида приборов
  thzdaq-core/src/thzdaq_core/   # слои: cli → adapters → application → domain (import-linter)
    domain/              # без файлов, часов и своих потоков
      parameters.py      # декларативные параметры процедур и настроек устройств
      station/           # config, kinds (подустройства), ports (AttributePort, GuardedPort),
                         # safety (пределы стенда, безопасное состояние, Guard), station,
                         # profile (формат профиля: словари, миграции)
      measurements/      # procedure, plots (PlotSpec), catalog (процедуры по имени),
                         # procedures/ (встроенные, список BUILTIN)
      data/              # measurement (DTO)
      sis/               # калибровка SIS-блока, размагничивание
    application/         # юзкейсы: assembly (сборка), dispatch (права, вопрос человеку,
                         # обработчик), handlers/ (по обработчику на операцию), events (шина),
                         # runs и runner (измерения), polling, devices, approvals и policy,
                         # scripts (сессии скриптов), processes (процессы скриптов), custom
                         # (свои измерения), workspaces, windows, local (LocalLab), ports
    adapters/            # json_store (измерения), yaml_profiles (профили и .history/),
                         # legacy_profiles (импорт settings.ini), instrument_states (state.json),
                         # library (measurements/), processes (процессы скриптов)
    cli/                 # station (thzdaq-station: профили как файлы, без демона)
  thzdaq-analysis/src/thzdaq_analysis/   # чистые расчёты, только numpy: iv, noise,
                                         # shot_noise, two_sb, decibels
  thzdaq-api/src/thzdaq_api/    # контракт по областям (devices, measurements, station, daemon,
                                 # scripts, …), catalog, events, errors, measurement_file; remote
                                 # (RemoteLab), host (файлы демона), lanes, lab (connect()),
                                 # tools и present (агенты), workspace, interpreters
                                 # (Python скриптов рабочей папки)
  thzdaq-daemon/src/thzdaq_daemon/   # compose (точка сборки), server (HTTP + SSE), process
  thzdaq-cli/src/thzdaq_cli/     # thzdaq: daemon, devices, measurements, scripts, agents, …
  thzdaq-mcp/src/thzdaq_mcp/     # thzdaq mcp: инструменты агентов по MCP stdio
  thzdaq/                        # мета-пакет PyPI
  thzdaq-gui/src/thzdaq_gui/
    app.py               # точка входа (composition root): тема, сессия, окно
    main_window.py       # окно: строит доки, меню и тулбар, одна раскладка
    docking.py           # DockSpace: доки по именам, куда открываются, их состояние
    dock_names.py        # имена доков (graph:…, device:…), измерений (measure:…), полей их форм
                         # (measure:…/поле) и кнопок панели (run:start) в одном месте
    guide.py             # WindowGuide: что агенты просят у окна (ui_*), ответы через демон
    overlay.py           # OverlayGuide: подсветка места окна с коротким текстом
    graph_docks.py, device_docks.py   # доки графиков и устройств: за GraphHub и станцией
    code_docks.py        # файлы скриптов вкладками в доке Editor (docks/tabbed.py, docks/code.py)
    console_docks.py     # Python-консоли вкладками в доке Console (docks/console.py)
    kernel.py            # ядро консоли (ipykernel) и клиент jupyter_client в своём потоке
    workspace_menu.py, workspace_settings.py   # рабочая папка в меню File; её настройки:
                         # Python скриптов (модель models/interpreter.py)
    console_output.py    # вывод консоли: блоки, цвета ANSI, места traceback — ссылки
    editor.py            # редактор скриптов (и поле ввода консоли): правка кусками, серый
                         # текст подсказки, Ctrl+I
    review.py            # правка текста кусками (difflib) без Qt: принять/отклонить кусок или все
    review_bar.py, ask_box.py   # ✓/✗ кусков и полоса над текстом; поле Ctrl+I
    assistant/           # ассистент без Qt: provider (OpenAI-совместимый chat/completions),
                         # keys (keyring), prompt (системный промпт), conversation (цикл),
                         # hints (что спросить у модели о коде и что взять из ответа)
    measure_forms.py     # формы измерений (за каталогом), по требованию
    runbar.py, run_controls.py   # панель сверху: список, ⚙, запуск; кнопки запуска
    popup.py             # выпадающее окошко под кнопкой (параметры под ⚙)
    session.py           # Lab (демон), профиль, папка, измерения окна, очередь вызовов
    bridge.py            # события Lab → сигналы Qt в потоке окна
    viewer.py            # окно графиков одного измерения (--plot)
    docks/               # setup, devices, measure, data, log, assistant (чат),
                         # providers (серверы моделей ассистента)
    models/              # модели вида на QtCore: run, device, daemon, console, assistant,
                         # hints (вопросы о коде к модели, один владелец), …
    graphs.py            # окна графиков и маршрутизация записей
    forms.py             # формы из параметров, выбор устройств по слотам
    measurements.py      # модель таблицы измерений
    settings.py          # реестр (сборка / исходники), папки программы
    exit_dialog.py, theme.py, resources/docks.css, resources/arrows/, wheel.py, iv_analysis.py
    updates.py, update_dialog.py, updater.py, version.py   # обновления из GitHub Releases
stations/                # профили стендов (YAML)
main.py                  # запуск GUI (--serve — демон) и вход PyInstaller
cli_main.py              # вход собранного thzdaq-cli
release.py               # выпуск версии
```

Тесты: `uv run pytest` из корня (GUI — offscreen).

## 4. Ключевые абстракции

### 4.1 Transport — «физический порт»
Два уровня:
- `Link` — физическое соединение построчно (`SocketLink`, `SerialLink`, `VisaLink`) со своим `RLock`.
- `Transport` — доступ одного прибора к линку: `write`, `read`, `query`, `transaction()`.
  `MessageTransport` пишет напрямую, `PrologixTransport` перед командой выбирает GPIB-адрес
  (`++addr` только при смене) и читает через `++read eoi`.

```python
@dataclass(frozen=True)
class ConnectionSpec:
    kind: str                 # socket | serial | prologix | prologix_usb | visa | http | modbus_tcp | modbus_rtu
    host: str | None = None
    port: int | None = None   # для prologix по умолчанию 1234
    serial_port: str | None = None
    gpib: int | None = None
    resource: str | None = None   # VISA, "GPIB0::19::INSTR"
    timeout: float = 2.0
    read_delay: float = 0.0
    baudrate: int = 9600
    write_termination: str = "\n"
    read_termination: str | None = "\n"   # None — чтение кусками с паузой (SIS-блок)
```
- GPIB: Prologix Ethernet, Prologix USB (через serial) и любой VISA-ресурс (NI GPIB-USB-HS,
  Keysight 82357B, USBTMC/LXI); VISA — опциональная зависимость `thzdaq-instruments[visa]`.
  Приборы за шлюзом serial→Ethernet — обычный `socket` с нужными терминаторами.
- `TransportPool.acquire(spec)`: один линк на физическую точку (`spec.link_key`), подсчёт
  ссылок, линк закрывается последним `transport.close()`; Prologix настраивается один раз.
  Соединения выводятся из адресов приборов, в профиле их нет.
- Восстановление: таймаут или обрыв помечают линк сломанным (`Link.broken`), следующая
  транзакция сначала переподключается и выбрасывает опоздавшие данные; запись сама не
  повторяется. После переподключения Prologix заново шлёт `++mode`/`++auto` и `++addr`
  (`invalidate()`). `pool.links()` — соединения со статусом и приборами, `pool.reset(key)` —
  переоткрыть, `pool.abort(key)` — прервать зависшее чтение из другого потока (сокет —
  `shutdown`, serial — `cancel_read`).
- Неиспользуемые TCP-соединения закрываются (`pool.close_idle`, в приложении — после 5 с
  простоя): прибор R&S с подключённым клиентом остаётся в remote (панель заблокирована,
  второй клиент может не подключиться). Следующая команда переподключается, Prologix
  настраивается заново. Serial не закрывается: открытие порта перезагружает Arduino.
- `query` держит блокировку линка от записи до чтения: приборы за одним Prologix не
  перемешивают команды, а измерения, мониторинг и ручное управление идут параллельно.
- HTTP (YIG на NI, сетка, Sumitomo REST) и Modbus (чоппер) не построчные: драйвер открывает
  клиент (`JsonHttpClient`, `PymodbusRegisters`) сам; в тестах клиенты подменяются.
- `FakeLink` записывает команды и отвечает по сценарию — на нём тестируются драйверы.
- У каждого драйвера есть `connection(...)` с рекомендуемыми настройками связи; Setup
  подставляет их кнопкой «Recommended connection».

### 4.2 Instrument, каналы и подустройства
```python
class Instrument:                     # база драйверов и симуляторов
    channel_class: type[Channel] | None
    channel_keys: tuple               # физические каналы модели: (1, 2, 3), ("A", "B", "C", "D")
    subdevices: dict[str, SubdeviceType]   # что пользователь добавляет: sis_bias, sis_coil
    def channel(self, key) -> Channel
    def part(self, accessor, key)     # channel(key), ctrl(key), ... по виду подустройства
    @classmethod
    def fixed_channels(cls) -> tuple  # каналы, которые показываются сами по себе

class ScpiInstrument(Instrument):     # текстовые команды поверх Transport
    def query_float / query_int / query_bool(...)   # мусор в ответе → InstrumentResponseError
    def identify(self) -> str                       # *IDN?
    def send_raw(self, command, answer) -> str | None   # RawCommands: команда как набрана

@dataclass(frozen=True)
class SubdeviceType:                  # вид функционального устройства на приборе
    title: str
    accessor: str = "channel"         # метод прибора, отдающий часть
    keys: tuple = ()                  # допустимые каналы, DEV1–DEV4
    part_class: type | None = None    # класс части — возможности известны без открытия
```
Два вида «частей» прибора:
- **каналы** — физические одинаковые выходы, заданные моделью (CH1–CH3 блока питания, входы
  LakeShore, каналы YIG); есть всегда, показываются внутри дока прибора;
- **подустройства** — функциональные устройства, которые настраивает пользователь: на
  SIS-блоке каждый DEV может быть смещением (`sis_bias`, `channel()`) или катушкой
  (`sis_coil`, `ctrl()`). Если подустройства используют `channel`, каналы отдельно не показываются.

### 4.3 Capabilities — маленькие интерфейсы (ISP)
Интерфейс описывает одну возможность; прибор или его часть реализует несколько. Это `Protocol`
только из методов, поэтому реестр выводит возможности драйвера из класса (`issubclass`).
```python
class Identifiable(Protocol):       def identify(self) -> str
class RawCommands(Protocol):        send_raw(command, answer) -> str | None  # мимо защиты
class Switchable(Protocol):         set_output(bool), get_output() -> bool
class VoltageSource(Protocol):      set_voltage(V), get_voltage() -> V   # уставка
class CurrentSource(Protocol):      set_current(A), get_current() -> A   # уставка/предел
class VoltageCurrentMeter(Protocol): measure() -> ChannelReading         # факт
class FrequencySource(Protocol):    set_frequency(Hz), get_frequency() -> Hz
class PowerLevel(Protocol):         set_power(dBm), get_power() -> dBm
class PowerDetector(Protocol):      read_power() -> dBm                  # ошибка — исключение
class TunableFilter(Protocol):      tune(Hz) -> Hz, get_frequency()      # реально выставленная; без обратного чтения — последняя
class LoadSwitch(Protocol):         to_hot(), to_cold()
class Thermometer(Protocol):        read_temperature() -> K
class SpectrumAnalyzer(Protocol):   set_center_frequency/set_span/set_*_bandwidth, read_peak(), read_trace()
class NetworkAnalyzer(Protocol):    set_frequency_range(), set_points(), select_parameter(), set_averaging(), read_trace()
class VacuumGauge(Protocol):        read_pressure() -> Pa
class Rotator(Protocol):            rotate_to(deg), get_angle()
class Compressor(Protocol):         turn_on/off(), read_temperatures() -> K, read_pressures() -> Pa
```
SIS-смещение — это `VoltageSource + VoltageCurrentMeter`, канал блока питания —
`Switchable + VoltageSource + CurrentSource + VoltageCurrentMeter`. Единицы — СИ (К, Па) даже
там, где прибор отдаёт °C, psig или гПа: пересчёт в драйвере, обратный — только в интерфейсе.

Блоки питания реализуют канал один раз (`SupplyChannel`), вендор задаёт только SCPI-примитивы
(`_set_output`, `_set_voltage`, `_measure`, ...) — шаблонный метод вместо трёх копий.
Для каждой возможности есть контрактный тест (`tests/contracts.py`): симуляторы и драйверы на
`FakeLink` проходят одни и те же проверки — так держится LSP.

### 4.4 Величины
`Quantity` (`thzdaq_instruments.quantities`) — то, что часть прибора читает или задаёт: ключ,
название, единица (СИ, dBm, deg), вид (`float`/`bool`), get/set. Величины выводятся из
возможностей (`VoltageSource` → «Voltage setpoint, V», `VoltageCurrentMeter` → «Voltage» и
«Current» из одного `measure()`, `PowerDetector` → «Power, dBm», ...); драйвер добавляет свои
атрибутом `quantities` (закоротка SIS — `SHORT`, множитель и OEM-голова генератора —
`GENERATOR_QUANTITIES`, состояние чоппера — `CHOPPER_QUANTITIES`). `read_values(part)` читает
все сразу, общий вызов делается один раз. Из величин строятся доки устройств, мониторинг и
графики — новый драйвер сразу получает рабочий док.
- `choices` — список значений текстовой величины (OEM `OFF`/`ON`).
- `persistent=True` — **конфигурация прибора** (множитель, OEM start/stop): хранится в профиле
  (`settings` прибора), остальные величины — **уставки**, последние значения в реестре.
- Приставки СИ — одна таблица `units.SI_PREFIXES` (p … G, 10⁻¹²…10⁹), `prefixes_for(unit)`:
  для dBm, dB, deg приставок нет, для K — только K и mK.

**Сохраняемое состояние** (`thzdaq_instruments.state`, `KeptState`) — то, что о приборе знает
только программа: сетка (`ArduinoGrid`, её симулятор) не читает своё положение и считает угол
по своим движениям (`thzdaq_instruments.angle.CountedAngle`). Прибор сообщает каждое изменение
тому, кто следит (перед движением «двигается к X», после — «стоит на X»), и принимает его назад
при открытии; где оно хранится, ему всё равно. Движение, которое не закончилось (демон
остановили, связь оборвалась), оставляет угол неизвестным: чтение и движение отказывают с
просьбой обнулить, действие `zero` («Set zero») делает текущее положение 0° без движения.
Отказ самой сетки (её ответ с ошибкой) оставляет её где была. В ядре станция зовёт `on_open`
при открытии прибора; `application/kept.py` (`KeptStates`) отдаёт прибору запись порта
`InstrumentStates` и пишет туда его изменения; запись другого драйвера (профиль сменился) не
применяется. Адаптер — `adapters/instrument_states.py`: JSON-файл демона (`state.json`, у
симулятора `state-sim.json`, рядом с `daemon.json`), записи по id прибора, файл целиком
атомарно под замком; ошибка записи — в лог, движение не останавливает.

### 4.5 Станция — профиль стенда
Профиль (`stations/*.yaml`, версия 2) — приборы и устройства на них. Id называет тип прибора
(`power_supply_3`, `power_meter_1`), вендор и модель — в `driver` и `title`:
```yaml
version: 2
name: lab
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
    settings: {frequency_multiplier: 18}   # конфигурация, последняя записанная в прибор
  power_supply_1:
    driver: rigol.dp832a
    connection: {kind: socket, host: 169.254.0.14, port: 5555}
  power_meter_1: {driver: rs.nrx, connection: {kind: socket, host: 169.254.2.20, port: 5025}}
```
- **Устройство** — то, чем пользуются: сам прибор (`power_meter_1`), его канал
  (`power_supply_1:2`) или настроенное устройство (`sis_bias_1`); id уникальны в станции.
- **Виды настроенных устройств** (`domain/station/kinds.py`) — только подустройства драйвера
  (`sis_bias`, `sis_coil`); настройки вида описаны параметрами с единицами — из них строятся
  форма в Setup и проверка. Генератор, измеритель мощности — одно устройство; умножитель
  частоты — конфигурация генератора (`settings` прибора), а не отдельное устройство.
  Переключатель ПЧ и питание YIG — любой канал блока питания (`Switchable`), который выбирают
  в 2SB-измерении; полярность («upper sideband when on») — параметр измерения.
- **Настройки прибора** (`settings`) при подключении в прибор не пишутся: ими заполняются поля
  дока, в прибор значения уходят по Set. Профиль обновляется после успешной записи или по
  «Take from device», если значение в приборе отличается от профиля.
- Устройства старых видов `frequency_multiplier`, `sideband_selector`, `switch` при чтении
  профиля отбрасываются с предупреждением в логе; множитель переносится в `settings` генератора.
- На одном DEV может быть несколько конфигов (разные смесители с разными смещениями и
  калибровками): `AttributePort` применяет настройки своего конфига перед каждым вызовом.
- `Station`:
  - `devices()` — список `DeviceInfo` (ссылка, название, вид, возможности) без открытия
    приборов: по нему строятся меню, доки и списки выбора в измерениях; `quantities(ref)`;
  - приборы открываются лениво, устройства кэшируются; `device(ref)` / `station[ref]`
    отдаёт устройство в `GuardedPort`: вызов, задающий уставку, проверяется по паспорту
    драйвера и разделу `safety` профиля до отправки команды, большое изменение идёт
    лесенкой (`docs/daemon.md` → «Защита приборов и образцов»); станция получает `pause`,
    которой ждут ступени;
  - `require(devices, requirements, pause, planned)` строит устройства для слотов измерения
    и проверяет возможности и значения, которые задаст прогон, сообщая обо всех проблемах
    сразу; ступени этих устройств ждут паузой прогона, её прерывает отмена;
  - `reconfigure(config)` принимает изменённый профиль и закрывает только приборы с новой связью;
  - `snapshot()` и `device_use(ref)` — метаданные для измерения;
  - `simulate=True` (или `simulate: true` у прибора) подставляет симулятор с `sim_options`;
  - `connections()` / `reset_connection(key)` — общие соединения и их сброс, `abort(refs)` —
    прервать ввод-вывод приборов, которыми пользуется зависшее измерение.
- Профили версии 1 (с ролями) читаются и переводятся в устройства автоматически.
- Импорт старого `settings.ini` (`[Configs]`, QVariant — нужен PySide6): SIS-конфиги одного
  хоста сливаются в один блок с устройствами `sis_bias_N`/`sis_coil_N`, названия становятся
  `title`; адаптеры Prologix пропускаются; NRX/YIG/чоппер — из старых констант `state`.
- CLI: `thzdaq-station import-legacy | show | check [--simulate] [--devices ...]`.

### 4.6 Procedure — измерение без Qt
```python
class IFNoise(Procedure):  # добавляется в список BUILTIN (procedures/__init__.py)
    name = "if.noise_temperature_vs_frequency"
    title = "SIS Tn-IF"
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
  `--device bias=sis_bias_1` в CLI). `slot_kinds` подсказывает вид: слот `bias` предлагает
  SIS-смещения, а не каждый канал блока питания. `slots()` может зависеть от параметров:
  Tn-V с `hot_cold=True` требует ещё `load`.
- Параметры декларативны: значения в СИ, у каждого — единица показа и масштаб, поэтому форма
  и CLI работают в ГГц/мВ, а код — в Гц/В. Типы: `Float`, `Int`, `Bool`, `Choice`,
  `MultiChoice`, `FloatList`, `StringList`, `Sweep(start, stop, points)`. У параметра есть
  группа (`group`, названия — `Group` в `procedures/common.py`): форма показывает параметры
  по группам под разделителем с названием. Правило «показывать, если» — `shown_if` процедуры
  (`shown_while(When("hot_cold", (True,)), "t_hot", ...)`; правила миксинов и подклассов
  складываются, `conditions()`): параметр используется, только пока все его условия
  выполнены (`used(name)`); неиспользуемый не проверяется по пределам прибора (`planned()`).
  В контракте это `ParameterInfo.group` и `shown_if` (`Condition`); форма GUI прячет такие
  поля, CLI и MCP пишут «used when».
- `guide` процедуры — методика для агентов и ассистента: что сделать до запуска, как идёт
  измерение, на что смотреть в результате. Его отдаёт `describe_procedure`
  (`ProcedureInfo.guide`, в тексте инструмента — «how to measure»); у каждой встроенной
  процедуры он есть (тест).
- Ключ процедуры — `<группа>.<что меряем>_vs_<что меняем>` (`thzdaq_api.procedures`).
  Прежние ключи — одна таблица `RENAMED` (старый → новый) там же; `current_name()` понимают
  каталог (запуск и описание из CLI, MCP, `lab.run`), разрешения скриптов `run:`, графики
  файлов (`saved_plots`), Data (текущее название, старое в подсказке) и запомненные значения
  форм GUI (`saved_procedure`).
- `ctx["slot"]` — устройство; `ctx.record(table, **values)` — строка таблицы измерения и
  событие для графиков; `ctx.sleep()` просыпается сразу при отмене; `ctx.on_exit(callback)` —
  восстановление состояния (LIFO) при успехе, отмене и ошибке. Процедура не знает про доки
  (DIP): интерфейс подписывается по `PlotSpec`.
- Процедуры (`thzdaq list`):

  | Имя | Что делает | Слоты |
  |---|---|---|
  | `sis.current_vs_voltage` | I-V | bias |
  | `sis.current_vs_coil_current` | ток SIS от тока катушки (I-CL) | coil, bias |
  | `sis.demagnetization` | размагничивание | coil |
  | `sis.current_vs_grid_angle` | ток SIS от угла сетки | grid, bias |
  | `sis.power_vs_voltage` | P-V: мощность ПЧ вместе с I-V | bias, detector |
  | `sis.noise_temperature_vs_voltage` | Tn-V: P-V с hot/cold (Y, Tn от V), опционально углы сетки | bias, detector, load (+grid) |
  | `sis.reflection_vs_frequency` | S-параметры VNA по развёртке смещения | bias, vna |
  | `if.amplifier_noise_vs_voltage` | IF health check: Rd в двух точках, P-IF, шум ПЧ-усилителя | bias, detector, if_filter |
  | `if.noise_temperature_vs_frequency` | Tn-IF: P-IF hot/cold, Y и Tn | detector, if_filter, load |
  | `if.power_vs_frequency` | Power-IF YIG: P-IF без нагрузок | detector, if_filter |
  | `monitor.values_vs_time` | выбранные величины устройств во времени (P, T, V, I, давление, ...) | любые |
  | `two_sb.if_balance` | P-IF обоих каналов для пар смещений | sis1, sis2, if_selector, detector, if_filter |
  | `two_sb.lo_rf_balance` | токи накачки от частоты LO или RF | sis1, sis2, lo/test_tone (+detector) |
  | `two_sb.sideband_ratio` | test tone в каждой полосе → SRR по ПЧ; опц. Y/Tn | + test_tone, detector или spectrum, load |
  | `two_sb.noise_temperature` | Y и Tn верхнего и нижнего каналов | sis1, sis2, if_selector, detector, if_filter, load |
  | `two_sb.bias_optimization` | карты SRR и Tn по сетке SIS1×SIS2 | все слоты 2SB |

### 4.7 Runner и прогоны
- `MeasurementRunner(station, store, observers)` (`application/runner.py`, чистый Python;
  хранилище — порт `MeasurementRepository`, время начала и конца ставит раннер): проверяет
  параметры, строит
  устройства слотов (`devices={"bias": "sis_bias_1"}`), создаёт `Measurement` со снимком стенда
  и описанием использованных устройств, вызывает `run(ctx)`, выполняет cleanup и ставит статус
  `completed | cancelled | failed`. Нет устройства — ошибка до создания файла.
- Графики прогона (`active_plots` по параметрам и приборам) раннер кладёт в `plots` измерения
  до открытия файла, `ctx.plot` дописывает туда же: файл рисует себя сам, как бы ни менялась
  процедура. Файлы, записанные раньше (`plots` нет), берут графики процедуры по ключу (через
  `RENAMED`) и добавленные из метаданных `plots`.
- Файл идущего измерения — порт `MeasurementWriter` (`store.open(measurement)`): каждая
  запись дописывается сразу, остальное (комментарий, метаданные, графики) — не чаще раза в
  `update_interval` (5 с) и только если изменилось; в конце — целый файл.
- `RunObserver`: `on_started / on_record / on_progress / on_log / on_finished`; упавший
  наблюдатель не останавливает измерение. Один раннер — одно измерение за раз,
  `cancel()` из другого потока.
- `Runs` (`application/runs.py`) — измерения в демоне: каждое в своём потоке со своим
  раннером, поэтому измерения идут параллельно; номер выдаётся до старта. Сначала прогон
  берёт аренды своих устройств (4.12), потом наблюдатель публикует события:
  `measurement_started` с графиками, записи пачками, прогресс, лог, конец. Уставки прогона
  (`quantity_set`) — не чаще раза в 0,1 с на величину, поэтому развёртка в тысячи точек —
  несколько событий в секунду. Отмена и прерывание — операции; `abort` прерывает
  ввод-вывод приборов зависшего измерения. Своё измерение скрипта (`lab.measurement`) —
  сессия: измерение, строки которого пишет клиент (`Sessions` в `application/scripts.py`,
  операции — `thzdaq_api.sessions`).

### 4.8 Данные
- DTO (`domain/data/measurement.py`): `Measurement` — номер (id), процедура, статус, время начала и
  конца (до миллисекунд), комментарий,
  параметры, `devices: {слот: DeviceUse}`, `tables`, результаты, снимок стенда, метаданные.
  `Table` хранит данные по колонкам словарём, как старый стор (`{"voltage": [...], ...}`), и
  описание колонок `Column(key, title, unit)` — графики и экспорт знают, что и в каких единицах.
  Названия и единицы обычных ключей — `KNOWN_COLUMNS`, процедура может уточнить `columns`.
- `MeasurementStore(root)` (`adapters/json_store.py`): `<root>/<дата>/<id>_<процедура>.json` (`000042_sis_current_vs_voltage.json`)
  — один JSON на измерение. Id — число: `next_id()` берёт наибольший номер в именах файлов
  папки данных плюс один, поэтому номера растут между запусками программы; у файлов старых
  версий остаются текстовые id. Без хранилища раннер нумерует измерения в процессе.
  Запись идёт через временный файл (сбой оставляет предыдущую полную версию). Пока измерение
  идёт (`RunningFile`), JSON — его описание без строк, а строки дописываются по одной в
  соседний `<id>_<процедура>.jsonl`; в конце пишется целый JSON, `.jsonl` удаляется. Файл со
  статусом `running` читается как `interrupted` вместе со строками `.jsonl`: убитый процесс
  не теряет ни одной (`docs/daemon.md`, «Долгие измерения на диске»). Комплексные числа и
  NaN/inf сохраняются без потерь.
  `export_csv()` — таблица в CSV с заголовками «Voltage, V».
- Формат файла описан в контракте (`thzdaq_api.measurement_file`): клиенты читают и рисуют
  файлы без core, а события `measurement_records` несут строки в той же кодировке
  (`thzdaq_api.data`).
- Хранилища — по рабочим папкам (`application/workspaces.py`, 4.12): измерение ложится в
  `data/` папки, которую назвал клиент, без неё — в `data/` домашней папки демона; номер
  выдаёт демон, один на все папки.
- CLI: `thzdaq procedures | describe <процедура> | run <процедура> [--device
  bias=sis_bias_1] [--set voltage=0:7:351] | measurements | show <файл>`.

### 4.9 Интерфейс (`thzdaq-gui`)
Организация старого приложения на Qt Advanced Docking System (PySide6-QtAds): каждая часть —
док, который можно поставить куда угодно, отцепить или свернуть в боковую панель.
- **Базовые доки** закреплены на боковых панелях, без крестика и без меню: Setup и Data
  слева; Log, Processes, Daemon, Editor и Console снизу; Assistant справа. Их можно развернуть, пристыковать (пин ADS) и
  снова свернуть, но не закрыть; раскладка, сохранённая до появления базового дока, не знает
  его, и он возвращается на свою боковую панель (`DockSpace.restored`).
- **Editor** — скрипты вкладками внутри одного базового дока, простыми вкладками Qt, а не
  доками ADS (`docks/tabbed.py`, `TabbedDock`: крестик или средняя кнопка закрывают вкладку,
  если владелец согласен, вкладки переставляются, без вкладок — подсказка и «Open a
  script…», «New measurement…»; так же устроена Console). `CodeDocks` держит вкладку на
  файл (и на текст, сохранённый измерением): открыть открытый — сделать его вкладку текущей и
  перейти к строке, ● у несохранённого, закрыть с несохранённым — вопрос; любое открытие
  разворачивает Editor. Вкладка скрипта из библиотеки, открытая или ставшая текущей, выбирает
  его измерение на панели (`Session.custom_of`, `RunBar.want`: ещё не описанное демоном — как
  только появится в списке, если человек не выбрал другое). Вкладка файла (`docks/code.py`) — Save, Check, Run, Ask, вставка кусков,
  изменения с диска, VS Code, «In console» (выделенное или файл — в консоль), Fix у вывода
  упавшего запуска. Процесс
  скрипта ведёт в Processes к вкладке своего файла: `code:/путь` — место внутри дока, его
  показывает владелец (`DockSpace.show_inside`).
- **Console** — Python-консоли вкладками в базовом доке (тот же `TabbedDock`; `ConsoleDocks`,
  `console_docks.py`): «New console» в «+», на пустом доке и в Ctrl+K (раздел Consoles: и
  открытые консоли). У каждой своё ядро — процесс `ipykernel` на Python скриптов рабочей
  папки окна (`thzdaq_api.console`: команда, окружение; сторона ядра — `thzdaq_api.kernel`,
  подсказки стенда); команду `Kernel` получает при каждом старте, поэтому идущее ядро держит
  свой Python до Restart. `Kernel` (`kernel.py`) — единственный владелец ядра: поток с циклом asyncio, в нём
  асинхронные менеджер и клиент `jupyter_client`; сообщения ядра — сигналы Qt в поток окна.
  Удаляет `Kernel` сессия (его родитель Qt) в потоке окна: сам себя он не удаляет — удаление
  из своего потока или пока поток жив портит память Qt. `ConsoleModel` (`models/console.py`)
  — открытие (`from thzdaq import *`, `lab = connect()`), очередь кода, пока ядро стартует,
  история, дополнение; вкладка (`docks/console.py`) — вывод сверху (`console_output.py`),
  поле ввода — редактор скриптов (`ConsoleInput`). Закрыть вкладку — остановить ядро;
  закрыть окно — остановить все и дождаться их. Последний блок, упавший с traceback,
  модель хранит (`ConsoleModel.failed`: код, traceback без цветов, блоки до него) до
  следующего блока — для Fix.
- **Правка кусками** (docs/daemon.md, «Правки ассистента и внешних агентов»): `Review`
  (`review.py`, без Qt) — правка текста по кускам difflib, у каждого ✓/✗; что значит
  нерешённый кусок, говорит её источник: правка с диска уже сделана (✗ откатывает), предложение
  ассистента не принято, пока нет ✓, сравнение с диском — моё, пока не взят кусок файла.
  `CodeModel` делает правку с диска (`outside` — нет несохранённого, `compare` — по кнопке
  баннера конфликта); редактор (`CodeEditor.show_review`) показывает строки правки (уходящие
  красным и зачёркнуты, приходящие зелёным, номера строк — по тексту как он сейчас), ✓/✗ у
  первой строки каждого куска и полосу «… all» сверху, и не принимает ввод, пока не решены
  все; потом текст — текст правки (`review_ended`). Своё сохранение через демон окно не
  принимает за правку снаружи (`CodeModel.writing`).
- **Подсказки агента в коде** — функции редактора, поэтому и в файле, и в консоли:
  серый текст после паузы в наборе (Tab берёт, Esc и любая другая клавиша убирают, ответ на
  уже изменённый текст не показывается: вопрос отменяется), Ctrl+I (Ask) — поле под строкой,
  код по словам приходит предложением, Fix — правка текста упавшего запуска (файл: traceback
  вывода; консоль: упавший блок и блоки до него) тоже предложением. `HintsModel`
  (`models/hints.py`) — один владелец этих вопросов к выбранному серверу ассистента: каждый —
  `Request` того, кто спросил, ответ в потоке окна, отменённый или ушедший вместе со
  спросившим — выброшен; модель спрашивается в своём потоке без потока ответа. Что
  спрашивать и что взять из ответа — без Qt (`assistant/hints.py`: руководство `hints.md`,
  раздел своих измерений из `agents.md`, устройства стенда). Без сервера ничего не
  спрашивается: Ask и Fix выключены с подсказкой, почему. Модель только предлагает: код
  выполняет человек, права — его.
- **Assistant** — чат с моделью, которая работает со стендом теми же инструментами, что
  MCP-агенты (`thzdaq_api.tools`), как агент `assistant`: что она меняет, спрашивает человека
  карточкой подтверждения в окне. Без Qt (`assistant/`): клиент OpenAI-совместимого
  `chat/completions` с потоковым ответом, системный промпт (`assistant.md` и правила из
  `agents.md`, стенд сейчас, процедуры со слотами), цикл (вызовы → ответы модели, отказы и
  ошибки — тоже ответы, не больше 20 шагов на сообщение, Stop сразу). `AssistantModel`
  (`models/assistant.py`) запускает ход в своём потоке, сказанное приходит в поток окна
  сигналами в очереди; док (`docks/assistant.py`) показывает сообщения, вызов — свёрнутой
  карточкой («set_quantity sis_bias_1 voltage_set 1 mV → done», развёрнутая — аргументы и
  ответ). Серверы моделей — диалог (`docks/providers.py`): имя, URL, модель, ключ,
  температура и Test (отвечает ли сервер и принимает ли `tools`). Разговор не сохраняется.
- **Подсказки агентов** (`guide.py`, `overlay.py`; docs/daemon.md, «Подсказки в окне»):
  агент или ассистент видит окно структурой (`ui_state`: доки, кнопки панели, выбранное
  измерение и поля его формы — имена и значения), открывает док или измерение (`ui_open`),
  заполняет форму измерения, ничего не запуская (`ui_fill_measurement`), и подсвечивает
  место с коротким текстом (`ui_highlight`). Демон шлёт окну `ui_requested` по id окна
  (`Session.window`, он же в потоке событий); `WindowGuide` — единственный владелец этих
  запросов в окне: спрашивает `Places` (`reveal(имя)` показывает док, измерение, поле
  формы или кнопку панели и даёт виджет), `RunBar` (`described`, `form_state`, `fill`),
  форму (`ProcedureBox.fields`, `fill`, `field`) и `DockSpace` (`described`) и отвечает
  `answer_ui`. Окно, ставшее активным, говорит демону `window_active`. `OverlayGuide` —
  полупрозрачная рамка вокруг якоря и текст рядом поверх окна, где якорь (главное,
  плавающий док, окошко под ⚙); мышь проходит сквозь неё, она идёт за якорем и уходит от
  клика, Esc, ввода в якорь и вместе с ним; новая заменяет прежнюю.
- Меню **Devices** (док на каждый прибор и настроенное устройство), **Graphs** (окно на
  каждый вид кривой: I-V, P-V, Y-V, Tn-V, P-IF, P-t, ... и свои через «New graph…»),
  **Help** (обновления). Меню Measures нет: измерения — в списке на панели сверху.
- **Поиск доков** (`navigator.py`): каждое меню доков — поле поиска над деревом. Доки одного
  типа — ветка («SIS bias (2)», «Power supply (5)»; тип устройства — вид настроенного
  устройства или id прибора без номера, `power_supply_3` → Power supply; измерения — по
  группе SIS, IF, 2SB), тип с одним доком — просто строка; раскрытые ветки запоминаются в
  реестре (`navigator/expanded`). С текстом поиска список плоский: все слова должны
  встретиться в названии, типе, разделе или ref/драйвере; первым — точное название, затем
  начинающиеся с поиска. Клик по строке (или Enter) **показывает** док, где бы он ни был:
  открывает к докам своего вида, делает текущей вкладкой, разворачивает боковую панель,
  поднимает плавающее окно, даёт фокус и на 0,7 с обводит рамкой акцентного цвета. Глаз
  справа только открывает или закрывает док и показывает состояние: на экране (оранжевый),
  за другой вкладкой или в свёрнутой панели, закрыт (строка серая). **Ctrl+K** (на macOS
  ⌘K; «Find…» в правом краю тулбара подписан сочетанием своей системы) открывает тот же
  поиск по всем разделам поверх окна, с измерениями: строка измерения выбирает его в
  списке панели и открывает окошко его параметров (`Places`: строки доков показывает
  `DockSpace`, измерений — `RunBar`; меню или Ctrl+K закрывается до того, как строка
  показана, потому что окошко параметров — тоже всплывающее). Сочетание — действие окна (`QuickFind.action`) с
  контекстом всего приложения: работает из любого поля, дока и плавающего окна программы. Меню Qt меняет размер виджета-действия только при изменении
  действия, поэтому навигатор после раскрытия ветки «трогает» своё действие.
- **Главное окно** (`main_window.py`) только собирает части: создаёт доки, меню и тулбар,
  связывает сигналы и хранит одну раскладку (`window/docks`; раскладка другой версии — Lite
  и Pro — не восстанавливается, строится раскладка по умолчанию). Доки по именам и правила,
  где открывается закрытый док, — `DockSpace` (`docking.py`, отображение имя → док); имена
  доков (`graph:I-V`, `device:sis_bias_1`) и измерений (`measure:sis.current_vs_voltage`:
  так их называют Ctrl+K и Processes) составляются и разбираются только в `dock_names.py`,
  потому что их хранят сохранённые раскладки. Доки графиков следуют за `GraphHub`
  (`graph_docks.py`), доки устройств — за станцией (`device_docks.py`), формы измерений — за
  каталогом (`measure_forms.py`), обновления —
  `Updates` (`update_dialog.py`), предупреждение о молчащем приборе — `HangWatch`
  (`workers.py`).
- **Панель сверху** (`runbar.py`, `RunBar`), слева направо: список измерений, ⚙
  параметры, 📈 графики (иконка без надписи), комментарий (350 px — на 18 % короче, чем
  когда он занимал свободную ширину), Start, Check, Stop, Abort (когда его предлагает
  измерение), прогресс с состоянием («Running 42 %», «completed #12»); дальше Safe state и
  Find. **Список** — кнопка с меню: измерения по группам с разделителями и иконками (SIS,
  IF, 2SB, Monitor, свои — последними; иконка измерения — буква M в квадрате, у Monitor
  своя, `procedure_groups.py`; группа без измерений не показывается), выбранное — жирным;
  под ними «New measurement…» и «From an example…» (подменю примеров; оба —
  `CodeDocks.new_measurement` / `from_example`). Кнопка шириной по самому длинному
  названию, чтобы панель не прыгала. Выбор запоминается (`ui/measurement`); своё измерение
  исчезло вместе со скриптом — выбирается измерение по умолчанию (I-V). **Идущие
  измерения** крутят иконку (`theme.Spinner`, `mdi6.loading` с `qta.Spin`) — каждое в
  списке, их может быть несколько, и на кнопке списка, если идёт выбранное. Что идёт,
  говорит не виджет, а модель: `MeasureForms` слушает `RunStatus` каждой формы и
  сообщает `running_changed`. Таймер анимации qtawesome создаётся при первой отрисовке
  иконки и перерисовывает свой виджет; когда крутить нечего, он останавливается.
  **Параметры — окошко под ⚙** (`popup.py`, `DropDown`): всплывающее (`Qt.Popup`), без
  заголовка и кнопок окна; в нём только форма выбранного измерения — название, краткое
  описание, у своего — кнопка Code (`CodeDocks.open_custom`), сообщение, если скрипт не
  описан, и выбор графика для каждого объявленного графика; приборы по слотам (у монитора
  — дерево величин) и параметры. Ширина по содержимому, высота по содержимому, но не ниже
  края экрана под кнопкой — дальше прокрутка; при изменении содержимого (свернули секцию)
  окошко подстраивается (`LayoutRequest`). Закрывается кликом мимо, повторным ⚙ и Esc.
  Qt закрывает всплывающее окно по нажатию мимо и затем повторяет нажатие виджету под
  мышью — на самой ⚙ это открыло бы окошко снова; поэтому нажатие на ⚙ закрывает его без
  повтора (`WA_NoMouseReplay`, как у `QComboBox`). Выпадающие списки внутри — свои
  всплывающие окна поверх него и его не закрывают. Смена выбранного измерения при открытом
  окошке показывает его форму. Формы (`measure_forms.py`, `MeasureForms`) — по одной на
  измерение, строятся при первом запросе (окошко или запуск с панели) и живут до конца окна
  (скрытыми в окошке или в окне), поэтому введённое переживает закрытие окошка; последние
  значения при Start сохраняются в реестр, как раньше. Выбор другого измерения не
  останавливает идущее (оно видно в Processes).
  Состояние запуска — модель `RunStatus` в `ProcedureBox` (идёт ли, что делает, шаги,
  итог, можно ли Abort) с сигналами `status_changed` и `comment_changed`; кнопки,
  комментарий и прогресс — вид `RunControls` (`run_controls.py`) этой модели: строкой в
  панели и столбцом под сканом в доке устройства. Оба читают модель и вызывают
  `start`/`stop`/`abort`, а не
  виджеты друг друга. Раскладка по умолчанию: слева SIS bias и катушки, графики в центре.
  Колонка устройств в ней получает ширину по
  содержимому, графики — остальное (`fit_columns`), после первого показа окна: до него у
  сплиттера нет размеров, а содержимое строится уже после раскладки. Доки в раскладке по
  умолчанию открываются до переноса в свою группу — иначе ADS скрывал вкладку первого дока
  группы.
- **Содержимое доков.** При восстановлении раскладки ADS переносит в новые области все
  доки, и закрытые тоже, а Qt заново применяет стили ко всему дереву каждого перенесённого
  виджета. Поэтому содержимое доков устройств (`docks/body.py`, `DockBody`)
  создаётся при первом открытии дока и находится в доке, только пока он открыт;
  отсоединённое содержимое продолжает работать (мониторы, идущие измерения). Крестик прячет
  док, а не удаляет (`DockWidgetDeleteOnClose` выключен): введённые значения переживают
  закрытие; удаляются только доки, ушедшие из станции или каталога.
  Содержимое дока не задаёт ширину больше той, что может дать колонка (панель анализа
  I-V — в две строки), иначе Qt раздвигает сплиттер и сохранённые ширины сбиваются.
  Поэтому числовые поля (`forms.CompactDoubleSpinBox`) шириной по показанному значению, а не
  по диапазону, поля форм не растягиваются на всю ширину, выбор приставки в закрытом виде
  показывает только единицу, а путь профиля в Setup переносится по разделителям.
- **Setup** — профиль стенда: группа **Connections** (общие соединения: Prologix, сокеты, —
  кто на них, статус, обновляется сам, Reset) и карточки приборов (драйвер, связь, статус, Connect / Edit /
  Delete / Add device) с устройствами на них; формы добавления прибора (только настоящие
  драйверы, поля связи по виду адаптера, «Recommended connection») и устройства (вид, канал,
  имя, настройки). Изменения сразу уходят демону (`Session.update_profile` → операция
  `update_station`): он проверяет профиль, сохраняет его (прежняя версия — в `.history/`) и
  применяет; правку, которая задевает устройство идущего измерения, отклоняет с перечнем
  измерений. Доки пересоздаются, только если изменился их состав.
- **Доки устройств** строятся из величин (`fields.py`), строка на величину: уставка — поле
  с выбором приставки СИ («GHz — ×10⁹», выбор запоминается в реестре) и Set, измеряемая
  величина — показание и единица. Уставку не опрашивают: это то, что задали (читается один
  раз, чтобы заполнить поле, и для графика, если больше нечего строить — катушка). В прибор
  значение уходит только по Set или Enter, до этого поле в оранжевой рамке; On/Off, Read, Monitor с интервалом, Plot — измеренные
  величины в графики P-t, V-t, I-t, ... с окном по времени (по умолчанию 600 с); с первыми
  значениями монитора графики всех его величин выходят на экран, как графики запуска, каждый
  в своей группе (`GraphHub.show_monitor`: у SIS bias I-t и V-t рядом), один раз за запуск
  монитора. Группа **Configuration** — величины `persistent`
  (множитель и OEM генератора; единица показа, усреднение, время фильтра и апертуры, пределы
  NRX) с отметкой, если прибор отличается от профиля. Дополнительно: SIS bias — смещения
  (те же поля с приставками, µV/µA), калибровка (редактор с выражениями, запись в EEPROM),
  I-V скан; катушка — I-CL скан и размагничивание (сканы — те же процедуры, что на панели
  сверху, `ScanBox` со своими кнопками запуска и логом, поэтому свёрнуты по умолчанию; свёрнутый скан в заголовке пишет «Running 42 %»
  или «completed #12»); чоппер — состояние hot/cold, Hot/Cold
  (поворот по датчикам с выравниванием), частота и непрерывное вращение Start/Stop;
  компрессор; спектроанализатор и VNA — трасса.
  Прибору, которому нечего показать (SIS-блок — только подустройства), док не создаётся.
- **Формы измерений** (`docks/measure.py`: `ProcedureBox`, `MeasureForm`, у монитора
  `MonitorForm`, у своих — `docks/custom.py`): устройства по слотам (только подходящие),
  параметры (последние значения запоминаются). Запускает форму панель сверху, **что
  говорит запуск** (start, итог, путь файла, отказы) и **что печатает скрипт своего
  измерения** (построчно) — во вкладке Log внизу (`docks/log.py`): запись помечена
  измерением (`tell`), показывается под его названием, а выпадающий список над логом
  показывает всё или одно измерение (`All` / название). Скан в доке устройства (`ScanBox`)
  — та же форма со своими кнопками запуска и свёрнутым логом под ней. Devices, Parameters
  и Log скана — сворачиваемые секции
  (`collapsible.py`): свёрнутые Devices показывают выбор строкой («Bias: SIS1 · Detector: R&S
  NRX», у монитора — число величин и устройства), свёрнутый Log — последнюю строку; Log свёрнут
  по умолчанию. Свёрнуто или нет — в реестре (`sections/<процедура>/<секция>`, у сканов в доках
  устройств — `sections/scan/...`), общее для всех форм процедуры. Если при Start не выбрано
  устройство, Devices разворачиваются. Пока измерение идёт, заблокированы поля, а не секции:
  свернуть и развернуть их можно. `ProcedureBox.status_changed` — одна строка о ходе
  измерения для тех, кто показывает его в другом месте. Записи идут в окна графиков по
  `PlotSpec` (`where` отбирает записи графика); каждый запуск — свои кривые «#id устройство
  группа». **Графики запуска — на экране сразу по Start**, до первых данных:
  `Procedure.active_plots(quantities)` называет графики, которые запуск заполнит (по
  умолчанию все `plots`; P-V без hot/cold — без Y-V и Tn-V, SRR без «Y-factor afterwards» —
  без шумовых, монитор — графики единиц выбранных величин, `quantities(slot)` — величины
  устройства слота). Каждый из них выходит вперёд в своей группе вкладок, и два графика
  одного запуска никогда не делят группу (`GraphDocks.show_run`): график, который
  оказался бы во второй раз в группе, переходит в группу графиков, где впереди нет графика
  этого запуска, а если таких нет — группа делится к сетке 2 × 2 (справа от первой, под
  первой, под второй). Больше четырёх групп не создаётся: остальные графики ждут за
  вкладками. Открытые в своих группах графики не двигаются, так что раскладка пользователя
  сохраняется. Если после первого шага данные пришли в график, которого процедура не
  назвала, он присоединяется к графикам запуска тем же правилом.
  `Procedure.plot_window()` — окно по времени для живых кривых (монитор: параметр «Plot
  window»): график держит только последние секунды, данные измерения — всё.
  **Monitor over time** — дерево устройств: устройство раскрывается в свои величины (по
  умолчанию отмечены измеряемые, уставки можно добавить); выбор — записи `ref/key` параметра
  `watch`. Каждое значение — строка таблицы `samples` (время, устройство, величина, значение,
  единица, график), график выбирается по единице (`plot_for`). Если поток не завершился
  через 5 с после Stop, появляется **Abort**: прерывает соединения приборов измерения, и
  заблокированное чтение выходит с ошибкой (Python-поток убить нельзя). Сторожевой таймер
  возвращает форму в исходное состояние, если поток кончился без сигнала.
- Крестик группы закрывает только активную вкладку.
- **Графики** (`GraphHub`): окно на вид кривой, кривые из любых измерений; «Add curve» —
  измерение, таблица, колонки x/y с единицами; Remove hidden / all; анализ I-V (Rn, Rj, Q, щель).
  Живые точки копятся в `GraphWidget.points`, а кривые рисуются по таймеру не чаще раза в
  50 мс (`REDRAW_MS`, `flush`), сколько бы записей ни приходило; целое измерение (Plot, Add
  curve) рисуется сразу. Перо кривых — 1 px: сглаженное перо толще стоит при отрисовке в
  ~70 раз больше. С отрисовкой на каждую запись пером 2 px симулированный P-V (≈50 записей
  в секунду) с P-V и I-V на экране занимал GUI-поток отрисовкой на секунды, и зум, сдвиг,
  клики ждали.
  Цвет кривой выбирается один раз, при её создании: первый цвет палитры, которого нет на
  этом графике (`GraphWidget.free_color`); кривые не перекрашиваются, цвет удалённой
  достаётся следующей новой (по номеру кривой новая после удаления повторяла цвет).
  **Ключ и подпись.** `PlotInfo.title` — ключ графика (`p-t`, `I-V`, `Coil-t`): по нему
  график назван в окне (`GraphHub`), док (`graph:<ключ>`) в раскладке, `into=` скриптов и
  графики в файлах; он не меняется. `PlotInfo.caption` — то, что читает человек
  (`plot_caption`: обозначения и слова, «p–t   Pressure (time)», «I–t   Coil current
  (time)» у `Coil-t`): заголовок дока и графика, меню Graphs, Ctrl+K (там тире ищется
  дефисом). Подписи меняются свободно; общие для нескольких процедур — в
  `procedures/common.py`, графики по времени — у монитора.
  **Значения у курсора** (`CursorTag`): над областью графика рядом с мышью плашка x, y (у
  карты и z ячейки) в единицах осей; за областью графика и вне окна её нет.
  **Graphs** в `RunControls` (панель сверху и сканы в доках устройств): графики, которые заполнит
  запуск с параметрами и приборами формы (идущий — его графики), выходят на экран как при
  Start (`ProcedureBox.show_graphs`).
  Свои графики (New graph…) переименовываются, им задаются подписи осей, они удаляются и
  запоминаются в реестре (`graphs/custom`); док своего графика назван ключом (`custom1`),
  поэтому раскладка переживает переименование.
- **Где открывается док.** Док устройства, у которого ещё не было места на
  экране, открывается плавающим посреди окна, размером по содержимому (не больше 90 %
  окна), — пристыковать его человек решает сам. Пристыкованный и закрытый — возвращается на
  своё место: ADS держит закрытый док в его группе, а пустую группу — скрытой в сплиттере;
  плавающий и закрытый — снова плавает там, где был. ADS добавляет док только в группу (или
  сразу показывает плавающим), поэтому док без места добавляется в группу и тут же её
  покидает с пометкой «без места» (`unplace`, `flagAsUnassigned`): такой док ADS открывает
  плавающим, как док, которого не знает восстановленная раскладка. ADS оставляет такой док
  без родителя, поэтому родителем становится менеджер доков — иначе док переживал окно.
  Графики и файлы скриптов открываются по-своему: закрытый — в группу вкладок, где больше
  всего открытых доков его вида; первый — слева от колонки измерений, иначе справа от
  устройств, иначе на всё окно (`DockSpace.open_center`; «центр» ADS в окне, где уже есть
  доки, — это низ, поэтому он не годится). Колонки устройств и измерений получают ширину
  по `sizeHint` содержимого, не больше 40 % окна, а графики — остальное
  (`DockSpace.fit_columns`): ADS размечает новую область, пока содержимое `DockBody` ещё не
  построено, и при вставке перераспределяет соседей. Если запуск измерения вывел графики на
  экран или поделил их группу, группы его графиков делят место поровну (`even_out`: ADS даёт
  отделённой группе меньше), а колонки снова получают свою ширину; раскладку, где ничего не
  делилось, запуск не трогает. ADS прячет сплиттер, все доки которого закрыты, только в
  показанном окне, поэтому после раскладки, сделанной или восстановленной до показа окна,
  такие сплиттеры прячет `hide_empty_splitters` — иначе пустой сплиттер держал место, а
  открытый рядом график сжимался.  пустой сплиттер держал место, а открытый рядом график сжимался. Док сначала
  открывается и только потом переносится: ADS оставляет скрытой вкладку закрытого дока,
  перенесённого в новую область.
- **Processes** (`docks/processes.py`, `processes.py`) — всё, что сейчас идёт: измерения
  с панели, сканы в доках устройств («SIS I-V curve · SIS2»), опрос Monitor в доке устройства
  («Monitor · R&S NRX», «every 1 s»), непрерывное вращение чоппера. Строка: статус, прогресс
  (полоса без конца, если конца нет), время, «показать», Stop и Abort — только когда его
  предлагает сам док (измерение ждёт не отвечающий прибор); сверху «Stop all». «Показать» и
  двойной клик показывают, где он идёт: док процесса (свёрнутый скан разворачивается) или
  измерение — выбранным на панели, с открытым окошком параметров (`Places`). Процесс
  регистрирует виджет, который его запустил (`Session.processes.start`), и завершает, когда
  тот кончился; Process только вызывает виджет обратно. Вращение чоппера сверяется с
  `is_running()` прибора после каждой команды. Число процессов — на вкладке
  («Processes (3)»). Док — в нижней боковой панели рядом с Log.
- **Data** — таблица измерений сессии и открытых файлов: комментарий редактируется и сразу
  сохраняется в файл; Plot, Save as JSON, CSV, Details, папка данных. Диалоги файлов
  (открыть и сохранить измерения, CSV, профили станций) открываются в папке, выбранной в
  прошлый раз для этого вида файлов (`folders.py`, `Session.folders`, в реестре
  `folders/<вид>`); пока её нет или она пропала (вынутая флешка) — в папке по умолчанию:
  для измерений это папка данных сессии, для профилей — `stations` рядом с программой.
- Потоки: приборов окно не держит — всё идёт операциями демону (4.12). Вызовы идут в фоне в
  очереди сессии (`DeviceWorker`, `workers.py`): поток и очередь на прибор
  (`thzdaq_api.lanes`), поэтому вызов к зависшему прибору не задерживает остальные, а
  вызовы об одном устройстве идут по порядку; если вызов висит дольше 5 с, `HangWatch` пишет
  в журнал, какой прибор не отвечает (соединение сбрасывается в Setup → Connections, очередь
  прибора в демоне — `thzdaq daemon reset-lane`). События демона приходят в поток
  `RemoteLab`, мост (`bridge.py`) отдаёт их Qt-сигналами в GUI-поток; измерения идут в
  демоне, окно следит за ними по событиям (`models/runs.py`, `models/run.py`), свои и
  чужие (CLI, другое окно, скрипт) одинаково. Сборка мусора Python идёт только
  в GUI-потоке по таймеру (`GarbageCollector` pyqtgraph, `app.py`): запущенная в потоке
  прибора, она освобождала бы Qt-объекты не там. Перед удалением графика `close_views`
  отключает якорь легенды и закрывает вью: иначе GC позже портит память (PySide 6.8).
- Сколько бы окон ни было открыто (сборка и исходники вместе), приборами владеет один демон;
  окно с `--simulate` работает с демоном симулятора, который идёт рядом с настоящим.
- Тема (`theme.py`): тёмная палитра Fusion с оранжевым акцентом, стили доков по
  `focus_highlighting_dark.css` ADS (`resources/docks.css`), иконки Material Design (qtawesome).
  Стиль Fusion на всех ОС, поэтому поля на Windows и macOS одинаковы: строки, списки, спинбоксы
  и кнопки одной высоты (`FIELD_HEIGHT`), стрелки спинбоксов и списков — свои картинки в цветах
  темы (`resources/arrows/`: обычная, при наведении, неактивная), а не мелкие стрелки Fusion.
  `wheel.py`: колесо мыши меняет спинбокс или список только после клика в него, иначе
  прокручивает док.
- Обновления (Help → Check for updates): `updates.py` читает GitHub Releases (теги `vX.Y.Z`,
  архив `ThzDAQ_Windows_x64_<тег>.zip`), скачивает и распаковывает сборку во временную папку
  системы (`%TEMP%\thzdaq_update_*`). Апдейтер запускается, когда окно действительно
  закрывается (после вопроса о выходе); если выход отменили, скачанная сборка ставится при
  следующем закрытии. `updater.py` (только stdlib, собирается в `updater.exe`) ждёт выхода
  программы до 5 минут, заменяет файлы с резервом и откатом, сохраняет отредактированные
  профили `stations/`, удаляет скачанное (и при ошибке) и запускает новую версию. Остатки
  прошлых обновлений во временной папке (`thzdaq_update_*`, `thzdaq_updater_*`) старше часа
  удаляются при старте программы.
  Беты — pre-release с тегом `vX.Y.Z-beta.N` (номер беты сравнивается числом, `v0.0.6` новее
  всех своих бет); каждая бета — новый номер, а не пересборка того же тега: у того, кто её
  поставил, версия не изменится и исправление ему не предложат. Галочка «Show pre-releases»
  запоминается (`updates/prereleases`) и действует и на проверку при старте; пока её не
  меняли, беты предлагаются тому, кто сам сидит на бете.
- Запуск: `uv run python main.py --station stations/2sb.example.yaml --simulate`.

### 4.10 Реестр драйверов и симуляторы
```python
registry.register("rigol.dp832a", RigolDP832A, title="Rigol DP832A power supply", sim=SimPowerSupply)
registry.open("rigol.dp832a", connection, pool=pool, simulate=False, **options)
```
- `default_registry()` — все встроенные драйверы (`drivers.DRIVERS`) и симуляторы (`sim.*`).
- Возможности драйвера и его каналов выводятся из классов (`DriverInfo.capabilities`,
  `channel_capabilities`), `find(capability)` ищет подходящие драйверы.
- `open(..., simulate=True)` создаёт симулятор: приложение целиком работает на симуляторах
  (`--simulate`) — разработка без стенда, демо, тесты процедур.
- Симуляторы по умолчанию отвечают точными значениями (тесты на это опираются). `liven()`
  добавляет медленный дрейф и шум (`sim/lively.py`, `Wobble`) мощности, температуре, давлению,
  компрессору, току и напряжению SIS и выходам блоков питания; `Station(lively=True)` вызывает
  его у открытых симуляторов — так делают приложение и `thzdaq run --simulate`.
- Симулированный стенд связан нагрузкой: станция при `simulate` даёт симулированному
  измерителю мощности `load_position()` — положение открытого симулированного чоппера, и
  горячая нагрузка добавляет мощность, как приёмнику с шумовой температурой 60 K
  (`sim/power_meter.py`, `load_power`, Y ≈ 4,2 dB). Без этого «Y» был разностью дрейфа двух
  развёрток, снятых в разное время: случайного знака, и Tn при Y ≤ 0 dB не было вовсе.
- Процедуры с горячей и холодной нагрузкой (Tn-V по углу, Tn-IF, каналы 2SB)
  пишут в лог, если Tn не определена (Y ≤ 0 dB): «hot is not above cold at any point …
  did the load switch?» или число таких точек (`warn_without_contrast`). Такие точки не
  рисуются, и без строки в логе кривая просто пропадала.

### 4.11 Конфигурация и где что хранится
- **Профиль стенда** (`stations/*.yaml`) — приборы и устройства; редактируется в Setup.
- **Настройки** (`settings.py`) — в реестре Windows (`QSettings`, на macOS — plist, в Linux —
  INI): геометрия окна, раскладка доков, выбранное измерение, путь к последнему профилю, последние
  параметры и устройства каждого измерения, параметры анализа I-V. Области разделены:
  - `HKEY_CURRENT_USER\Software\ThzDAQ\ThzDAQ` — собранная программа (продовая);
  - `HKEY_CURRENT_USER\Software\ThzDAQ\ThzDAQ-dev` — запуск из исходников.

  Реестр лежит вне папки программы, поэтому обновление его не трогает, а новая версия
  читает ту же область. `--settings FILE` хранит настройки в INI-файле (переносная установка,
  тесты). Где лежат настройки и данные, показывает Help → About.
- **Серверы моделей ассистента** — в настройках (`assistant/providers`, выбранный —
  `assistant/provider`), их ключи — в хранилище системы (`keyring`: Credential Locker
  Windows, связка ключей macOS), не в реестре. Где хранилища нет, ключ живёт до закрытия
  программы, и диалог это говорит.
- **Демон** — в домашней папке (папка программы): `daemon.json` (последний профиль, таймаут
  простоя, права агентов; у симулятора — `daemon-sim.json`); во временной папке системы (или
  `THZDAQ_DAEMON_DIR`) — его файл хоста, замок и лог (`thzdaq[-sim]-host.json`,
  `-daemon.lock`, `-daemon.log`).
- **Состояние приборов** (угол сетки) — `state.json` демона рядом с `daemon.json`, у
  симулятора `state-sim.json` (раздел 4.4): не в реестре (его видит только GUI) и не в
  профиле (засорил бы `.history/`).
- **Файлы** — рядом с программой, а не в текущей папке процесса (у собранной программы она
  зависит от ярлыка или апдейтера): `data/` — измерения и `data/dumps/`, `stations/` —
  профили, `measurements/` — свои измерения стенда. **Рабочая папка** эксперимента — папка
  с `thzdaq.toml` (`thzdaq init`): её `data/`, `scripts/` и `stations/` — копии профиля, с
  которыми в ней мерили; команды в ней и ниже работают в ней, окно открывается в ней
  (`thzdaq gui`, `--workspace`).
  Апдейтер заменяет только файлы из релиза: `data/` и всё, что не входит в сборку, остаётся,
  в `stations/` отредактированные профили сохраняются и добавляются только новые.
- **Выход** спрашивает, как в старом приложении: сохранить раскладку окна, сделать дамп
  всех измерений сессии в один файл
  (`data/dumps/dump_<дата>_<время>.json`, список `Measurement.to_dict()`) и остановить ли
  демон: по умолчанию — только если в нём нет измерений и других клиентов (CLI, агента,
  другого окна); измерения, оставленные в демоне, идут дальше. Перед выходом графики
  pyqtgraph закрываются явно (`close_plots()`).
- Аргументы запуска: `--station`, `--simulate`, `--workspace` (папка, в `data/` которой
  ложатся измерения), `--settings`. GUI — клиент демона (`docs/daemon.md`): `--simulate`
  выбирает демон-симулятор, `main.py --serve` запускает сам демон.

### 4.12 Демон и клиенты
Замысел, решения и вехи — `docs/daemon.md`; здесь — как устроено сейчас.

- **Один хозяин приборов.** Демон (`thzdaq-daemon`) — единственный процесс, который открывает
  приборы; окно, CLI, MCP-агенты, скрипты и консоли — его клиенты. Демон симулятора — другой
  процесс со своими файлами и настройками: оба идут одновременно, `--simulate` клиента
  выбирает демон симулятора. Один на машину держит замок ОС; клиент, не нашедший демон,
  запускает его сам (`thzdaq_api.host.connect_or_start()`, под замком запуска: два клиента —
  один демон). Сборка запускает демон как `ThzDAQ.exe --serve`.
- **Сборка** (`compose.py`): станция профиля на часах процесса, полосы приборов, сохраняемое
  состояние (`state.json`), рабочие папки с хранилищем измерений, библиотека своих измерений
  (`measurements/` домашней папки) и юзкейсы (`application/assembly.py`) с процессом демона в
  роли порта `DaemonControl`.
- **Операции.** Операция — Struct аргументов в своей области `thzdaq_api` (`devices.py`,
  `measurements.py`, `station.py`, …), в списке `catalog.py`; у неё один обработчик без
  состояния (`application/handlers/<область>.py`, явный список в `assembly.py`). Всё извне
  идёт через `Dispatcher` (`dispatch.py`): права по origin звонящего (`policy.py`: человек
  делает, что просит, а опасное подтверждает его клиент; агенту — что разрешает настройка
  демона `allow / ask / deny`, но профиль, ответы за человека и сырую запись — никогда), вопрос
  человеку (`approvals.py`: карточка в окне или `thzdaq approvals watch` в терминале; ждёт вне
  блокировок), обработчик, ошибка — `LabError` с кодом. Значения с единицами приходят
  строками и разбираются один раз, в демоне. Процедуры внутри демона говорят со своими
  устройствами напрямую.
- **Сервер** (`server.py`): `ThreadingHTTPServer` на localhost; операция — POST `/ops/<имя>` с
  токеном из файла хоста (без токена, с чужим `Host` или с `Origin` браузера — отказ),
  `/health`, `/status`, события — SSE `/events`. Поток событий — слушатель (`Clients`): кто он
  (`gui`, `cli`, `mcp`, `script`, …), его pid и окно; по ним статус показывает клиентов, окно
  решает, предлагать ли остановить демон при выходе, а демон — когда он простаивает.
- **События** (`application/events.py`, `EventBus`): нумерованные, в кольцевом буфере на
  10 000. Слушатель слышит событие в потоке, который его опубликовал, а поток клиента хранит
  только своё место в буфере, так что шина никого не ждёт. Переподключившийся клиент называет
  последнее событие (`Last-Event-ID`) и догоняет пропущенное; отставший дальше буфера
  получает `Resync` и берёт снимок (`get_snapshot`, `get_run_snapshot`). Раз в 2 с — `heartbeat`
  (клиенты, измерения, проблемы); поток, молчащий 6 с, клиент считает оборванным.
- **Полосы** (`thzdaq_api.lanes`): поток и очередь на прибор. Задания одного прибора идут по
  порядку, приборы не ждут друг друга, приборы за одним Prologix ждут блокировку соединения.
  Задание дольше 5 с — проблема в статусе, `reset_lane` даёт прибору новую полосу. Опрос по
  подписке (`polling.py`): один опрос на устройство с самым коротким интервалом подписчиков,
  показания — событие `values`; опрос, ещё ждущий прибора, не ставится снова.
- **Аренды** (`domain/leases.py`): измерение берёт свои устройства `read`, `shared` или
  `exclusive` (развёртка); конфликт — только с `exclusive` и только без явного `share`.
  Человек на конфликт получает вопрос (док прибора, терминал CLI), агент — карточку; принятый
  конфликт записывается в оба измерения. Изменение профиля, задевающее занятое устройство,
  отклоняется.
- **Процесс** (`process.py`): файл хоста (порт, токен, версии) пишется, когда демон слушает, и
  удаляется в конце. Демон заканчивается по `stop` (graceful отказывает, пока идут измерения
  или скрипты; `cancel` и `abort` заканчивают их и ставят безопасное состояние профиля), по
  `restart`, по сигналу или после `idle_timeout` (600 с) без слушателей, измерений и скриптов;
  `kill` клиента — для того, кто не отвечает. Статус (`thzdaq daemon status`, док Daemon):
  профиль, открытые приборы, клиенты, измерения, скрипты, полосы, соединения, опросы,
  проблемы, память, число потоков и последние ошибки лога.
- **Потоки демона:** главный ждёт остановки; `http` и по потоку на запрос и на каждый поток
  событий; `idle` смотрит, не простаивает ли демон; полоса на прибор; `polling`; `idle
  connections` закрывает соединения, простоявшие 5 с; поток на измерение; на скрипт — поток,
  который ждёт конца его процесса и дочитывает его лог.
- **Клиенты:**
  - `RemoteLab` (`thzdaq_api.remote`) — HTTP + SSE с переподключением; `LocalLab`
    (`application/local.py`) — те же юзкейсы в процессе (тесты core и GUI). Контрактные
    тесты core идут на обоих.
  - Окно (`thzdaq-gui`) — модели вида (`models/`) вызывают операции в очереди сессии, мост
    (`bridge.py`) отдаёт события Qt-сигналами, `models/runs.py` ведёт каждое измерение (и
    начатое не окном) в одну модель запуска; формы — из `ProcedureInfo`, графики — из
    `PlotInfo`, анализ — операциями. Индикатор и док Daemon, баннер «нет связи» с запуском.
  - CLI (`thzdaq`) — команды поверх операций; вопросы — в терминале (`--yes`; без терминала —
    «нет»); `thzdaq approvals watch` отвечает на вопросы агентов за человека.
  - MCP (`thzdaq mcp`) — инструменты агентов (`thzdaq_api.tools`, короткие ответы с
    единицами — `present.py`), тот же набор, что у ассистента окна; origin — `mcp:<агент>`.
  - Скрипты: `from thzdaq import connect` — Python-клиент (`thzdaq_api.lab`), устройства
    объектами; `lab.measurement` — своё измерение-сессия (`thzdaq_api.script`).
    `thzdaq script start` — скрипт процессом демона (`ScriptProcesses`, лог — событиями
    `script_output`) с правами того, кто его запустил; `--allow` — что человек разрешил ему
    без вопроса. Скрипт агента спрашивает, как агент.
  - Консоль окна — процесс ядра со своим `lab = connect()` (origin `console`, права
    скрипта человека); как она устроена в окне — 4.9.
- **Рабочие папки** (`thzdaq_api.workspace`, `application/workspaces.py`): папка с
  `thzdaq.toml` — её `data/`, `scripts/` и `stations/`; клиент находит её вверх от текущей
  папки и передаёт демону (`workspace` у `start_measurement` и у сессий скриптов); без неё
  измерения идут в `data/` домашней папки демона. Изменённый профиль оставляет в папке свою
  копию. Номер измерения выдаёт демон, один на все папки.
- **Python скриптов рабочей папки** (`thzdaq_api.interpreters`, М4, шаг 4): `python` в
  `thzdaq.toml` (`.venv`, окружение uv или conda, любой интерпретатор), иначе свой Python
  программы. Правило у одного владельца, спрашивает его тот, кто запускает: демон — для
  своего измерения (папка из `start_measurement`), CLI и окно — для `start_script` (уходит
  уже выбранный), окно — для ядра консоли. Окно (File → Workspace settings…) показывает
  найденные окружения и проверяет выбранное: оно запускается, Python не ниже 3.11, `thzdaq`
  ровно версии программы, `ipykernel` для консоли. Каталог своих измерений описывается
  Python программы — он один на все папки.

## 5. SOLID — как выполняется

| Принцип | Решение |
|---|---|
| SRP | Драйвер — только протокол прибора; Procedure — только логика измерения; Runner — исполнение; Measurement/Store — хранение; док — отображение и управление |
| OCP | Новый прибор = драйвер + регистрация (док строится из величин); новое измерение = файл Procedure (док и графики — из параметров и `PlotSpec`); новый вид устройства = запись в `kinds.py` |
| LSP | Все реализации capability взаимозаменяемы: контрактные тесты одной пачкой для всех драйверов и симуляторов |
| ISP | Мелкие capability вместо «толстого» класса прибора; процедура зависит только от возможностей своих слотов |
| DIP | Процедуры и интерфейс зависят от интерфейсов; юзкейсы — от портов (`application/ports.py`); конкретику (станцию, хранилища, драйверы) собирает демон (`compose.py`), окно — `app.py` |

## 6. Тестирование
- Чистые расчёты (`thzdaq-analysis`, `sis`) — обычные юнит-тесты.
- Драйверы — на `FakeLink` и эмуляторах протоколов (SCPI-строки и разбор ответов).
- Контрактные тесты capability: один набор на каждом драйвере-фейке и симуляторе.
- Станция, профили, импорт старого `settings.ini`, процедуры и раннер — на симуляторах.
- Юзкейсы — контрактные тесты core (`test_lab_*.py`): одни и те же на `LocalLab` и на
  `RemoteLab` к демону, который служит по HTTP в процессе теста (`thzdaq-daemon/tests/
  test_remote_contract.py`). Демон как процесс (запуск клиентом, рестарт, kill, простой) — в
  подпроцессе или в потоке со своими файлами (`test_process.py`); CLI и MCP — на своих
  клиентах к тем же юзкейсам.
- Интерфейс — offscreen на `LocalLab`: окно собирается, доки следуют за Setup, измерение
  строит графики и сохраняет JSON, раскладка сохраняется и восстанавливается, колесо не
  меняет поля без фокуса; окно на демоне по HTTP — `test_served.py`.
- CI (`.github/workflows/ci.yml`) гоняет все тесты на Windows на каждый пуш; релиз — тесты,
  сборка и smoke-запуск собранного exe.

## 7. Этапы переписывания

1. **Каркас** ✅: uv workspace, `thzdaq-instruments` (errors, units, readings, capabilities,
   transport с пулом и блокировками, `Instrument/Channel`, реестр, симуляторы).
2. **Драйверы** ✅: Rigol DP832A, R&S HMP2030 / NRX / ZVA67 / FSEK30, Keithley 2200,
   Agilent E8247C, Scontel SIS, NI YIG (HTTP), Modbus-чоппер, LakeShore 336, SRS SR830,
   Sumitomo F-70 (RS-232 и REST), Arduino grid — с симуляторами (Pfeiffer отключён до
   переписывания),
   эмуляторами протоколов и контрактными тестами.
3. **Станция** ✅: `thzdaq-core` — профиль стенда (YAML), `Station`, импорт `settings.ini`,
   CLI `thzdaq-station`.
4. **Измерения** ✅: `Procedure`, параметры, `PlotSpec`, `MeasurementRunner`, все измерения
   старого приложения и ветки `2sb` как процедуры, CLI `thzdaq`.
5. **Интерфейс** ✅: доки QtAds и перспективы как в старом приложении поверх нового ядра.
   Вместе с ним роли заменены устройствами на приборах (профиль версии 2), добавлены величины
   и подустройства, данные — DTO с сохранением в JSON.
6. **Удаление старого** ✅: `api/`, `store/`, `interface/`, `threads/`, `utils/`, `measures/`,
   `settings*.py/.ini` удалены; приборы продового `settings.ini` перенесены в `stations/lab.yaml`.
7. **Сборка и релизы** ✅: PyInstaller (`build.sh`, `build.bat`), релизы Windows x64 из GitHub
   Actions по тегу (`release.py`), обновление из программы.
8. **Исправления после v0.0.2** ✅ (`docs/workplan.md`).
9. Мерж в `master`.
10. **Демон и клиенты** — вехи М1–М4 `docs/daemon.md`: приборы в демоне, GUI и CLI — его
    клиенты, права и MCP, скрипты и рабочие папки, ассистент в окне.

## 8. Чего не делаем
- Не тянем bluesky/QCoDeS/EPICS целиком — берём идеи.
- Не вводим библиотеку единиц (pint) — соглашение «СИ внутри, пересчёт на границе интерфейса».
- Не делаем DI-фреймворк и плагины через entry points — хватает реестров и `app.py`.
- Не переходим на asyncio — опрос и измерения в потоках с блокировками транспорта.

## Ссылки
- QCoDeS, создание драйверов: https://microsoft.github.io/Qcodes/examples/writing_drivers/Creating-Instrument-Drivers.html
- Bluesky / ophyd, устройства из сигналов: https://nbviewer.org/github/bluesky/tutorials/blob/main/Ophyd/01%20-%20Group%20Signals%20into%20Devices.ipynb
- NOMAD CAMELS: https://arxiv.org/abs/2402.07548
- PyMeasure, GUI из Procedure: https://pymeasure.readthedocs.io/en/latest/tutorial/graphical.html
- Qt Advanced Docking System: https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System
