# ThzDAQ — управление СИС-смесителем и измерения его характеристик
__Разработана в рамках государственного задания ФИАН № FFMR-2024-0013 "ИССЛЕДОВАНИЕ КОСМИЧЕСКИХ ОБЪЕКТОВ И ЯВЛЕНИЙ В СУБМИЛЛИМЕТРОВОМ ДИАПАЗОНЕ ДЛИН ВОЛН; АСТРОФИЗИКА И КОСМОЛОГИЯ"__

Репозиторий — uv workspace из трёх пакетов:

| Пакет | Что внутри | Зависимости |
|---|---|---|
| `packages/thzdaq-instruments` | драйверы приборов, транспорт (TCP, serial, Prologix, VISA, HTTP, Modbus), симуляторы | pyserial, requests, pymodbus |
| `packages/thzdaq-core` | профиль стенда и роли, процедуры измерений, исполнитель, данные, анализ, CLI | numpy, pyyaml |
| `packages/thzdaq-gui` | настольное приложение (PySide6, pyqtgraph) | PySide6, pyqtgraph |

Устройство и принципы — в [docs/architecture.md](docs/architecture.md).

## Системные требования
- Python 3.11, [uv](https://docs.astral.sh/uv/)
- Windows 10 64-bit, macOS 11+, Linux

## Установка и запуск
```bash
uv sync
uv run python main.py --station stations/lab.yaml
```
Без железа — на симуляторах:
```bash
uv run python main.py --station stations/2sb.example.yaml --simulate
```

## Интерфейс
Как в старом приложении — доки Qt Advanced Docking System, которые расставляются как удобно,
и перспективы (сохранённые раскладки) в тулбаре:
- **Base → Setup** — приборы стенда: добавить, изменить, удалить, подключиться; на приборе —
  устройства (SIS bias и катушка на SIS-блоке, LO ×18 на генераторе, переключатель IF на канале
  блока питания).
- **Devices** — док на каждый прибор и устройство: значения, установка, мониторинг и вывод на
  графики P-t/V-t/I-t, у SIS — смещения, калибровка, I-V/I-CL сканы и размагничивание.
- **Measures** — док на каждое измерение: устройства, параметры, Start/Stop.
- **Graphs** — окно на каждый вид кривой (I-V, P-V, Y-V, Tn-V, P-IF, ...), кривые из любых
  измерений («Add curve»).
- **Base → Data** — таблица измерений: комментарии, графики, JSON, CSV.

## Стенд
Приборы и устройства описываются в YAML-профиле (`stations/*.yaml`), который редактирует док
Setup: `lab.yaml` — продовый стенд из старого `settings.ini`, `2sb.example.yaml` — пример 2SB.
Id называет тип прибора (`power_supply_3`), вендор и модель — в `driver` и `title`.

```bash
uv run thzdaq-station show stations/lab.yaml
uv run thzdaq-station check stations/lab.yaml --simulate
```

## Данные
Каждое измерение сохраняется по ходу в `data/<дата>/<id>_<измерение>.json`: параметры,
использованные устройства и таблицы данных по колонкам с названиями и единицами
(`{"voltage": [...], "current": [...]}`). При выходе программа спрашивает, сохранить ли
раскладку окна и сделать ли дамп всех измерений сессии в `data/dumps/`.

Настройки (раскладка, перспективы, последние параметры) хранятся в реестре Windows:
`HKCU\Software\ThzDAQ\ThzDAQ` у собранной программы и `HKCU\Software\ThzDAQ\ThzDAQ-dev` при
запуске из исходников. Данные (`data/`) и профили (`stations/`) лежат рядом с программой.
Обновление не трогает ни реестр, ни `data/`, ни отредактированные профили.

## Измерения без интерфейса
```bash
uv run thzdaq list
uv run thzdaq describe sis.iv_curve
uv run thzdaq run sis.iv_curve --station stations/lab.yaml --device bias=sis_bias_1 --set voltage=0:7:351
```

## Тесты
```bash
uv run pytest
```

## Сборка .exe или .app
Linux/macOS:
```bash
sh build.sh
```
Windows:
```batch
build.bat
```
Результат — `dist/ThzDAQ` с папкой `stations` рядом с исполняемым файлом.

## Релизы и обновления (Windows x64)
Готовые сборки публикуются в [GitHub Releases](https://github.com/yarvod/ThzDAQ/releases):
архив `ThzDAQ_Windows_x64_vX.Y.Z.zip`, распаковать в папку с правом записи (не в Program Files).

Выпустить версию:
```bash
uv run python release.py 0.3.0
```
Скрипт записывает версию в `packages/thzdaq-gui/src/thzdaq_gui/version.py`, коммитит, ставит тег
`v0.3.0` и пушит. GitHub Actions (`.github/workflows/release.yml`) прогоняет тесты, собирает
`build.bat`, проверяет запуск и публикует релиз. Версия вида `0.3.0-beta.1` (или `-rc.1`) уходит
как pre-release; следующая бета — следующий номер (`0.3.0-beta.2`), а не пересборка того же тега.
Беты предлагаются тем, кто отметил «Show pre-releases» в окне обновлений или уже сидит на бете.

В программе: **Help → Check for updates…** показывает релизы и ставит выбранный. Приложение
скачивает архив, закрывается, `updater.exe` заменяет файлы (старые — в резерв, при ошибке
возвращаются) и запускает новую версию. Свои профили в `stations/` и данные в `data/` не
трогаются: из нового релиза добавляются только профили, которых ещё нет. При запуске
сборка сама проверяет наличие новой версии и показывает кнопку в строке состояния.
