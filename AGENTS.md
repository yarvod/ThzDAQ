# Repository Guidelines

## Project Structure & Module Organization

ThzDAQ is a uv workspace for SIS mixer control and measurements; see `docs/architecture.md` for the design and `docs/backlog.md` for ideas not taken up yet.

- `packages/thzdaq-instruments` (`thzdaq_instruments`): capability interfaces, quantities (readable/settable values with units derived from capabilities), fixed channels and sub-device types of instruments, transports (TCP, serial, Prologix, VISA, HTTP, Modbus) with a shared pool and per-link locks, instrument drivers in `drivers/`, simulators in `sim/`, driver registry. No Qt, no numpy.
- `packages/thzdaq-core` (`thzdaq_core`): station profiles with instruments and their configured devices, device kinds (`station/`), procedures with device slots and the runner (`measurements/`), measurement DTOs and the JSON store (`data/`), pure analysis (`analysis/`), SIS tools (`sis/`), CLIs `thzdaq` and `thzdaq-station`. No Qt.
- `packages/thzdaq-gui` (`thzdaq_gui`): PySide6 + PySide6-QtAds + pyqtgraph application in the layout of the old app: docks (`docks/`: Setup, device docks, measurement docks, Data, Log), graph docks (`graphs.py`), dock search (`navigator.py`: menus as a searchable tree by type, Ctrl+K), perspectives, dark theme with orange accents and qtawesome icons (`theme.py`). Docks only display and drive core objects.
- `stations/`: bench profiles (YAML, version 2: instruments with `devices`; ids name the kind of device, e.g. `power_supply_3`). `main.py` is the GUI entry point. `assets/` holds the pixel app icon (`thzdaq.ico`, `thzdaq.icns`, drawn by `assets/make_icon.py`; rerun it after changing the drawing). `firmware/` keeps device firmware (Arduino grid rotators).

Dependencies point one way: gui → core → instruments. Tests check that core and instruments never import Qt.

## Build, Test, and Development Commands

- `uv sync` creates or updates `.venv`; `uv lock` after changing any `pyproject.toml`.
- `uv run python main.py --station stations/2sb.example.yaml --simulate` runs the GUI on simulators.
- `uv run thzdaq run <procedure> --station <profile> [--simulate] [--device slot=device] [--set name=value]` runs a measurement without the GUI; `uv run thzdaq list` / `describe <procedure>` show what exists.
- `uv run thzdaq-station check <profile> --simulate` checks a bench profile.
- `uv run pytest` runs all package tests (GUI tests run offscreen); `uv run pytest packages/thzdaq-core` for one package.
- `sh build.sh` / `build.bat [name]` build the PyInstaller distribution into `dist/`.
- `uvx pre-commit run --all-files` runs Black, autoflake and hygiene hooks before committing.
- `uv run python release.py X.Y.Z` stamps `thzdaq_gui/version.py`, tags `vX.Y.Z` and pushes (`--again` moves an existing tag to the current commit after fixes and builds it again); `.github/workflows/release.yml` then tests, builds the Windows x64 zip and publishes the GitHub release that Help → Check for updates installs (`thzdaq_gui/updates.py`, standalone `thzdaq_gui/updater.py` built as `updater.exe`). `.github/workflows/ci.yml` runs the tests on every push.

## RTK (Rust Token Killer) — Required

RTK is installed and available on `PATH`. Agents must use RTK for every supported shell command by default to reduce command-output token usage. Do not run the raw equivalent unless exact unfiltered output is required, RTK does not support the command, or RTK fails. If RTK fails, fall back to the underlying command so work can continue.

Required command mappings include:

- `git status`, `git diff`, and `git log` → `rtk git status`, `rtk git diff`, and `rtk git log`.
- `git add`, `git commit`, `git push`, and `git pull` → the matching `rtk git ...` command.
- `rg` searches → `rtk rg <pattern> <path>`. Use `rtk grep` only when a `grep` binary is available on `PATH`.
- Large file reads → `rtk read <file>`.
- Directory listings and file searches → `rtk ls <path>` and `rtk find <pattern> <path>`.
- Python test runs → `rtk test uv run pytest ...`.

Run `rtk --version` to verify the installation and `rtk gain` to inspect token savings.

## Python and uv — Required

All Python environment and command interactions must go through `uv`: use `uv sync`, `uv add`/`uv remove` (with `--package <member>` for workspace packages), and `uv run ...`. Do not invoke `pip` directly or manually maintain a separate virtual environment. Keep every `pyproject.toml` and `uv.lock` committed and synchronized.

## Coding Style & Naming Conventions

Python with 4-space indentation, formatted by Black; autoflake removes unused imports. Values are SI inside the code (Hz, V, A, K, s, Pa), power in dBm, angles in degrees; display units live only in parameters and plots. New instruments implement capability interfaces (`thzdaq_instruments.capabilities`) and get a simulator plus contract tests; new measurements are `Procedure` subclasses registered with `@register_procedure`. Keep comments short and reserve them for non-obvious hardware, timing, or UI behavior.

## Testing Guidelines

Tests live next to each package (`packages/*/tests`, `test_*.py`, pytest). Drivers are tested against protocol emulators on `FakeLink` and the shared capability contracts in `packages/thzdaq-instruments/tests/contracts.py`; procedures run on simulators; GUI tests run offscreen. Hardware is never needed for tests. For changes that need real instruments, document the bench and steps used.

## Commit & Pull Request Guidelines

Short imperative messages, optionally with a conventional prefix (`feat:`, `fix:`, `docs:`). Pull requests describe the affected package, list manual test steps (bench, profile, simulate or hardware), mention profile changes in `stations/`, and include screenshots for visible UI changes.

No AI attribution anywhere in the history: commit messages, tags, pull requests and release notes carry no `Co-Authored-By` trailer for an AI assistant, no "Generated with …" line and no other mention of the assistant or model. The author of every commit is the repository owner. This rule overrides any default attribution an agent or tool would add.

## Security & Configuration Tips

Do not commit credentials or machine-specific settings. Keep generated outputs (`dist/`, `build/`, `data/`, logs) out of review unless they are intentional reference artifacts.
