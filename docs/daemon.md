# ThzDAQ: демон стенда, клиенты GUI/CLI/MCP и ассистент в GUI

## Зачем

Сейчас приборы держит GUI-процесс: `Session` → `Station`. Ручные команды и опрос идут через
`DeviceWorker` (поток на прибор), измерения — через `QtRunner` на док. CLI `thzdaq run`
открывает приборы сам. Если GUI открыт, два процесса делят Prologix/R&S, а lock-файл
(`app.instance_lock`) только предупреждает. Действия из CLI GUI не видит.

Цели:
1. Стенд держит один процесс — **демон** `thzdaq serve`. GUI, CLI, MCP (Claude Code, Codex по
   подписке) и ассистент — его клиенты. Работают одновременно, и любое изменение сразу видно
   всем.
2. Чат-ассистент в GUI. Провайдеры (URL, ключ, модель, параметры) в форме, активный
   выбирается. Ассистент видит устройства и их состояние, предлагает и делает измерения,
   подсвечивает, куда нажать. Интерфейс он видит как структуру (`ui_state`), без скриншотов.
3. Регулируемые права. Агент спрашивает разрешение или задаёт вопрос с вариантами, человек
   подтверждает, отклоняет или отвечает своим текстом.

Решено:
- сразу демон, GUI и CLI всегда клиенты, режима «GUI как хост» нет;
- API только localhost;
- после демона первыми идут CLI и MCP, потом права и ассистент.

## Архитектура

```
 GUI (клиент) ─┐  HTTP JSON + SSE    ┌──────────── thzdaq serve (демон) ─────────────┐
 CLI (клиент) ─┼─ 127.0.0.1, токен ─►│ API → LabService: операции, права, аренды,     │
 thzdaq mcp ───┤                     │ события, подписки опроса, раннеры, стор        │
 Ассистент ────┘                     │   → Station → полосы приборов → TransportPool  │
                                     └────────────────────────────────────────────────┘
```

- **Операции, а не прокси приборов.** Клиент никогда не держит объект прибора. Доступно:
  `devices`, `quantities(ref)`, `read(ref)`, `set(ref,key,value)`, `call(ref,action,args)`,
  `connections`, `reset_connection`, `procedures`, `describe`, `start(procedure, params,
  devices, comment)` → run id, `status`, `cancel`, `abort`, `measurements`, `measurement(id)`,
  `set_comment`, `station.get/update`, `subscribe_poll(ref, interval)`, UI-операции.

  У каждого вызова есть `origin` (gui, cli, mcp:<имя>, assistant). `Procedure.run` выполняется
  в демоне с настоящими драйверами, наружу идут только события.
- **Действия устройств декларативно**, как `Quantity`: `Action(key, title, params, danger)`.
  Они выводятся из возможностей (`LoadSwitch` → `to_hot/to_cold`, `Rotator` → `rotate_to`,
  `Compressor` → `turn_on/off`, `SpectrumAnalyzer/NetworkAnalyzer` → `read_trace`), драйвер
  добавляет свои (SIS: калибровка, чоппер: вращение). Так особые группы доков
  (`ChopperGroup`, `CompressorGroup`, `TraceGroup`, `SisBiasGroup`) становятся вызовами `call`.
- **Одновременные обращения:**
  1. полоса прибора — очередь и поток на прибор, перенос `_Lane` в core: ручные операции
     всех клиентов идут по порядку;
  2. блокировка линка (`Link.RLock`): байты на одной шине не перемешиваются;
  3. **аренда**: измерение занимает устройства своих слотов. Set/call от другого origin
     получают отказ или `ask`, чтение разрешено;
  4. **опрос по подписке**: один опрос устройства с наименьшим из интервалов подписчиков,
     значения рассылаются всем.
- **События** с порядковым номером:
  - `quantity_set`, `values`, `action_done`;
  - `measurement_started/records/progress/log/finished` (записи пачками);
  - `connection_changed`, `station_changed`, `lease_changed`;
  - `approval_requested/answered`, `ui_*`, `log`.

  Новый клиент получает **снимок**: идущие измерения с таблицами, уставки, соединения,
  аренды, номер последнего события. Дальше — поток SSE; после разрыва клиент догоняет с
  номера (кольцевой буфер; если пропущено слишком много, берёт новый снимок).
- **Жизненный цикл:**
  - клиент ищет демон по файлу `thzdaq-host.json` (порт, токен, pid, версия API) в той же
    временной папке, что `thzdaq.lock`; если демона нет, запускает `thzdaq serve` (у сборки —
    `ThzDAQ.exe --serve`, без окна) и ждёт готовности;
  - демон живёт, пока есть клиенты или идут измерения (плюс таймаут простоя);
    `thzdaq serve stop|status`;
  - версия API сверяется при подключении;
  - апдейтер останавливает демон, если нет измерений; иначе ждёт;
  - лог демона — файл в папке данных; уровни логов идут в Event log событием `log`.
- **Один писатель:** профиль стенда, данные (`MeasurementStore`), комментарии — только через
  демон. QSettings (окно, перспективы, последние значения форм) остаются в GUI.
- `--simulate` и профиль — свойства демона (`thzdaq serve --station X --simulate`); GUI
  меняет их операцией `station.load`.
- Транспорт: `ThreadingHTTPServer` из stdlib, JSON-запросы и SSE. Потоки, без asyncio и
  новых зависимостей. Слушает только 127.0.0.1, токен в заголовке.

## Пакеты и файлы

- `thzdaq-instruments`: `Action` и вывод действий из возможностей рядом с `quantities.py`;
  `actions` у драйверов (scontel, chopper, sumitomo, rs, arduino).
- `thzdaq-core`:
  - `service/service.py` — `LabService`;
  - `service/operations.py` — каталог и сериализация: `DeviceInfo`, `Quantity` →
    JSON-описания;
  - `service/events.py` — шина, буфер, снимок;
  - `service/leases.py`;
  - `service/polling.py`;
  - `service/lanes.py` — из `thzdaq_gui/workers.py::_Lane`, без Qt;
  - `server/http.py` — API и SSE;
  - `server/client.py` — `RemoteService` + поток событий;
  - `server/host.py` — файл хоста, автозапуск, остановка;
  - `cli.py` — команды через `RemoteService`.
- `thzdaq-gui`:
  - `session.py` — `RemoteService` вместо `Station`; Qt-мост событий в сигналы;
  - `workers.py` — `DeviceWorker`/`QtRunner` заменяются мостом;
  - `docks/devices.py` (~15 мест `worker.submit(lambda: device...)` → `service.set/call/
    subscribe_poll`), `docks/setup.py`, `docks/measure.py` (`start` → `service.start`, записи
    по событиям run id), `graphs.py`, `measurements.py`/`docks/data.py` (список из демона);
  - строка состояния «демон: OK/нет связи»;
  - `app.py` — подключение или запуск демона вместо прямой загрузки станции;
  - `updater.py`/`updates.py` — остановка демона.
- `thzdaq-mcp` (новый, зависит от core и `mcp`): `thzdaq mcp` по stdio — клиент демона.
- `main.py`, `build.sh`/`build.bat` — режим `--serve` в той же сборке.

## Этапы внутри работы

1. **Сервис в core** (без Qt, без сети): `LabService`, действия, события со снимком, аренды,
   опрос по подписке, полосы. Тесты на симуляторах.
2. **API и демон:** сервер, `RemoteService`, файл хоста, автозапуск, остановка, проверка
   версии, лог. Тот же набор тестов гоняется против `LabService` и против `RemoteService`.
3. **GUI-клиент:** `Session` на `RemoteService`, доки через операции, графики, Data, Event log
   по событиям, снимок при подключении, статус демона, остановка демона апдейтером. Прямого
   доступа к `Station` в GUI не остаётся.
4. **CLI-клиент:**
   - `thzdaq serve [start|stop|status]`, `devices`, `read`, `set REF KEY VALUE` (с
     единицами: `2.3mV`), `call`, `run` (стрим, Ctrl+C → cancel), `status`, `cancel`,
     `watch`, `measurements`, `--json`;
   - `--local` — старый режим без демона, для отладки.
5. **MCP:**
   - `thzdaq mcp`: инструменты = операции + `ask_user`, ресурсы = каталог процедур и
     методика;
   - `.mcp.json` для Claude Code и пример для Codex `config.toml`;
   - `docs/assistant/agents.md` — как мерить через `thzdaq`.
6. **Права и подтверждения:**
   - `Policy`: origin × класс операции (read, set, call, run, station, ui) → `allow | ask |
     deny`; режим «всё разрешено в simulate»;
   - `limits` величин в профиле стенда — проверяются всегда, независимо от прав;
   - `ask` блокирует вызов до ответа или таймаута, затем `pending` + `wait_answer(id)`;
   - в GUI карточка: Разрешить / Разрешить всегда / Отклонить + поле «сделай иначе»;
   - `ask_user(question, options, allow_text)` использует ту же карточку;
   - настройки прав — диалог в GUI, хранятся в демоне.
7. **Ассистент в GUI:**
   - `thzdaq_core/assistant/`: OpenAI-совместимый провайдер через `requests` со стримингом;
     цикл агента; контекст из `describe()`, устройств, соединений и `docs/assistant/*.md`;
     инструменты = операции с origin `assistant`;
   - диалог провайдеров: ключ в `keyring`, кнопка «Test», выбор активного;
   - док Assistant: чат, карточки вызовов, подтверждения и вопросы;
   - `OverlayGuide`: якоря-`objectName` у важных виджетов; рамка, стрелка, пузырь,
     «Далее» / «Сделай за меня»;
   - UI-операции `ui_state`, `ui_open`, `ui_fill_measurement` (`ParameterForm.set_values`,
     `DeviceSlotsForm`), `ui_highlight` идут через демон, поэтому доступны и MCP-агентам;
   - знания: `guide` у процедур и `docs/assistant/` с методикой.

## Переиспользуем
- `Station` целиком (`thzdaq_core/station/station.py`) — в демоне без изменений
- `Quantity`, `read_values` (`thzdaq_instruments/quantities.py`)
- `MeasurementRunner`, `RunObserver` (`thzdaq_core/measurements/runner.py`) — наблюдатель
  публикует события
- `Parameter.describe()` (`thzdaq_core/parameters.py`) → описания и JSON-схемы
- `_Lane` (`thzdaq_gui/workers.py`) → `service/lanes.py`
- `ParameterForm`, `DeviceSlotsForm` (`thzdaq_gui/forms.py`), `MainWindow.open_dock`
- `instance_lock` (`thzdaq_gui/app.py`) — та же временная папка для файла хоста
- `build_procedure`, `parse_devices`, `summarize` (`thzdaq_core/cli.py`)
- `MeasurementStore`, `read_json` (`thzdaq_core/data/store.py`)

## Проверка
- `uv run pytest`:
  - сервис: операции, аренды, подписки опроса, снимок и догон событий, лимиты, политика;
  - те же тесты через `RemoteService` с сервером в потоке;
  - CLI против демона в тесте;
  - MCP — список и вызов инструментов;
  - агент на фейковом провайдере;
  - GUI offscreen с демоном в потоке: set из CLI обновляет док, измерение из CLI рисуется,
    карточка подтверждения, подсветка находит якорь.
- Вручную на симуляторах:
  1. `uv run thzdaq serve --station stations/2sb.example.yaml --simulate`;
  2. `uv run thzdaq run sis.iv_curve --device bias=sis_bias_1`, во время работы открыть
     `uv run python main.py`: GUI показывает идущую I-V с уже набранными точками;
  3. `uv run thzdaq set sis_bias_1 voltage 2.3mV` во время I-V на нём: отказ из-за аренды;
     после конца — поле в доке обновилось, в Event log «cli»;
  4. закрыть GUI во время измерения: измерение продолжается, `thzdaq status` его видит;
  5. Claude Code с `.mcp.json`: «сними I-V» → карточка подтверждения в GUI;
  6. ассистент с Qwen: «как померить Tn 2SB» → план, заполненный док, подсветка Start.
- Сборка: `sh build.sh`, проверить `ThzDAQ --serve` и автозапуск демона из exe на Windows,
  а также что брандмауэр не задаёт вопрос.
- Обновить `docs/architecture.md` (раздел «Демон и клиенты», потоки, данные) и `AGENTS.md`.
