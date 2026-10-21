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

## Стенд
Приборы и роли описываются в YAML-профиле (`stations/*.yaml`): `lab.yaml` перенесён из настроек
старого приложения, `2sb.example.yaml` — пример стенда 2SB. Профиль редактируется в приложении
(Station → Edit…) или в любом редакторе.

```bash
uv run thzdaq-station show stations/lab.yaml
uv run thzdaq-station check stations/lab.yaml --simulate
```

## Измерения без интерфейса
```bash
uv run thzdaq list
uv run thzdaq describe sis.iv_curve
uv run thzdaq run sis.iv_curve --station stations/lab.yaml --role bias=sis1 --set voltage=0:7:351
```
Данные сохраняются в `data/<дата>/` (JSON Lines) по ходу измерения.

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
`build.bat`, проверяет запуск и публикует релиз. Версия вида `0.3.0-rc.1` уходит как pre-release.

В программе: **Help → Check for updates…** показывает релизы и ставит выбранный. Приложение
скачивает архив, закрывается, `updater.exe` заменяет файлы (старые — в резерв, при ошибке
возвращаются) и запускает новую версию. Свои профили в `stations/` и данные в `data/` не
трогаются: из нового релиза добавляются только профили, которых ещё нет. При запуске
сборка сама проверяет наличие новой версии и показывает кнопку в строке состояния.
