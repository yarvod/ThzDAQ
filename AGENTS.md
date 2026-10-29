# Repository Guidelines

## Project Structure & Module Organization

ThzDAQ is a uv workspace for SIS mixer control and measurements; see `docs/architecture.md` for the design and `docs/backlog.md` for ideas not taken up yet.

- `packages/thzdaq-instruments` (`thzdaq_instruments`): capability interfaces, quantities (readable/settable values with units derived from capabilities), fixed channels and sub-device types of instruments, transports (TCP, serial, Prologix, VISA, HTTP, Modbus) with a shared pool and per-link locks, instrument drivers in `drivers/`, simulators in `sim/`, driver registry. No Qt, no numpy.
- `packages/thzdaq-core` (`thzdaq_core`), in layers: `domain/` (station profiles with instruments and their configured devices, device kinds and ports in `station/`; procedures with device slots, plots and the catalog in `measurements/`; the measurement DTO in `data/`; pure analysis in `analysis/`; SIS tools in `sis/`), `application/` (the runner and its ports), `adapters/` (JSON measurements, YAML profiles, legacy `settings.ini`), `cli/` (`thzdaq`, `thzdaq-station`). No Qt.
- `packages/thzdaq-api`, `thzdaq-daemon`, `thzdaq-cli`, `thzdaq`: the daemon's contract and client, the daemon, the command-line client, the PyPI meta-package (`docs/daemon.md`; skeletons until milestone M1 fills them).
- `packages/thzdaq-gui` (`thzdaq_gui`): PySide6 + PySide6-QtAds + pyqtgraph application in the layout of the old app: the window only assembles the parts (`main_window.py`), docks by name and where they open (`docking.py`, names in `dock_names.py`), graph and device docks that follow the graphs and the station (`graph_docks.py`, `device_docks.py`), perspectives (`perspectives.py`), docks (`docks/`: Setup, device docks, measurement docks, Data, Log, Processes: what runs now, `processes.py`), graph docks (`graphs.py`), dock search (`navigator.py`: menus as a searchable tree by type, Ctrl+K), Lite and Pro modes (`modes.py`; Lite: one layout and the run bar on top, `runbar.py`; Pro: a dock per measurement and perspectives), run controls as a view of a run's status (`run_controls.py`), file dialogs that remember their folder (`folders.py`), dark theme with orange accents and qtawesome icons (`theme.py`). Docks only display and drive core objects.
- `stations/`: bench profiles (YAML, version 2: instruments with `devices`; ids name the kind of device, e.g. `power_supply_3`). `main.py` is the GUI entry point. `assets/` holds the pixel app icon (`thzdaq.ico`, `thzdaq.icns`, drawn by `assets/make_icon.py`; rerun it after changing the drawing). `firmware/` keeps device firmware (Arduino grid rotators).

Dependencies point one way: gui → core → instruments today, clients → api ← core → instruments as the daemon lands. `uv run lint-imports` checks the boundaries (contracts in the root `pyproject.toml`).

## Architecture Rules — Required

Fix the design, not the symptom. A change that only works with a hack is not done: restructure, or stop and ask.

- **One-way dependencies, no cycles.** Between packages gui → core → instruments; inside the GUI the entry point (`app.py`) → the window (`main_window.py`, it only assembles) → its parts (`docking.py`, `graph_docks.py`, `device_docks.py`, `perspectives.py`, `modes.py`, `runbar.py`) → docks (`docks/`) → widgets and view models (`forms.py`, `run_controls.py`, `collapsible.py`) → `theme.py`, `settings.py`, `dock_names.py`. A lower module never imports a higher one; it tells through Qt signals or callbacks it is given.
- **One owner per responsibility.** New behaviour goes into the object that owns the concept, not into `MainWindow` or into a widget that happens to be near. A concept lives in one place (dock names in `dock_names.py`, dialog folders in `folders.py`, a run's state in `RunStatus`); never parse or rebuild it elsewhere.
- **Polymorphism over branching.** What differs by mode, kind or device is an object asked for its answer (`Mode.dock_of`, capability interfaces), not `if mode == …` / `isinstance` chains spread over callers.
- **State in models, widgets are views.** Widgets show a model and call its methods; they never read another widget's labels, buttons or progress bars to learn state.
- **No hacks.** No flags that silence a path for one caller, no sleeps or timers to "let it settle", no retries, no `getattr(self, "_x", default)` for attributes that may not exist, no catch-all `except` to hide a failure, no dead code left behind. If a third-party library (Qt, ADS, pyqtgraph) needs a workaround, it lives in the module that wraps that library (ADS: `docking.py`), runs once at the point where the library's behaviour causes the problem, and its comment names that behaviour.
- **Prove it.** A bug fix reproduces the bug first (a test, or a script on simulators) and checks the fix against it.

### Target boundaries (daemon work, `docs/daemon.md` → «Пакеты, слои и границы»)

New code follows these boundaries now; existing code moves there during milestone M1.

- **Packages.** `thzdaq-api` (contract and client: operations, DTO, events, errors, the measurement file format, `RemoteLab`, `connect_or_start`; depends only on `msgspec`) ← `thzdaq-core` (domain and use cases) → `thzdaq-instruments`; `thzdaq-daemon` (process, HTTP + SSE, the server-side composition root) → core and api. Clients `thzdaq-gui`, `thzdaq-cli`, `thzdaq-mcp` import only `thzdaq_api`, never `thzdaq_core`, `thzdaq_instruments` or `thzdaq_daemon`. `thzdaq` is the PyPI meta-package with extras. Only the root `main.py` knows both the GUI and the daemon.
- **Layers in core.** `domain/` (station, `GuardedPort`, procedures, parameters, plots, measurement, leases, actions, analysis) ← `application/` (handlers, dispatcher, policy, approvals, runner, events, lanes, polling, scripts, workspaces, ports, `LocalLab`) ← `adapters/` (JSON store, YAML profiles, journal). The domain touches no files or clocks and starts no threads; it gets them through ports and the run context.
- **Use cases.** One operation = one Struct of arguments in `thzdaq_api.ops` and one stateless handler in `application/handlers/<area>/`, registered by an explicit list in the daemon's composition root. Every call from outside goes through the dispatcher: arguments → policy → handler → journal and event. A lease check and the write it guards run as one job in the device's lane. Procedures inside the daemon write through `GuardedPort` directly, not through the dispatcher.
- **Contract types.** DTO, operation arguments and events are `msgspec` Structs in `thzdaq-api`; JSON schemas are generated from them, never written by hand. Values with units travel as strings and are parsed once, by the daemon.
- **GUI.** View models in `thzdaq_gui/models/` are QObjects on QtCore that call `Lab`; they never import QtWidgets. Widgets show a view model and call its methods. One bridge turns `RemoteLab` events into Qt signals. Forms come from `ProcedureInfo` schemas, graphs from `PlotInfo`, analysis from daemon operations.
- **Vocabulary.** Quantity keys and units live in instruments, a procedure's name, slots and plots on its class, shared procedure parameters and axis labels in `domain/measurements/procedures/common.py`, operation names, event types and error codes in api, GUI settings keys in one GUI module. Use them by import; the duplicate test fails on repeated literals and function bodies across modules.
- **Enforcement.** import-linter contracts in the root `pyproject.toml` run in pre-commit and CI next to the duplicate test; a broken boundary fails the build.

## Build, Test, and Development Commands

- `uv sync` creates or updates `.venv`; `uv lock` after changing any `pyproject.toml`.
- `uv run python main.py --station stations/2sb.example.yaml --simulate` runs the GUI on simulators.
- `uv run thzdaq run <procedure> --station <profile> [--simulate] [--device slot=device] [--set name=value]` runs a measurement without the GUI; `uv run thzdaq list` / `describe <procedure>` show what exists.
- `uv run thzdaq-station check <profile> --simulate` checks a bench profile.
- `uv run pytest` runs all package tests (GUI tests run offscreen); `uv run pytest packages/thzdaq-core` for one package.
- `sh build.sh` / `build.bat [name]` build the PyInstaller distribution into `dist/`.
- `uvx pre-commit run --all-files` runs Black, autoflake, hygiene hooks and `lint-imports` before committing; `uv run lint-imports` checks the architecture boundaries alone.
- `uv run python release.py X.Y.Z` (or `X.Y.Z-beta.N`: a GitHub pre-release, a new number for every beta) stamps `thzdaq_gui/version.py`, tags `vX.Y.Z` and pushes (`--again` moves an existing tag to the current commit after fixes and builds it again); `.github/workflows/release.yml` then tests, builds the Windows x64 zip and publishes the GitHub release that Help → Check for updates installs (`thzdaq_gui/updates.py`, standalone `thzdaq_gui/updater.py` built as `updater.exe`). `.github/workflows/ci.yml` runs the tests on every push.

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

Python with 4-space indentation, formatted by Black; autoflake removes unused imports. Values are SI inside the code (Hz, V, A, K, s, Pa), power in dBm, angles in degrees; display units live only in parameters and plots. New instruments implement capability interfaces (`thzdaq_instruments.capabilities`) and get a simulator plus contract tests; new measurements are `Procedure` subclasses added to `BUILTIN` in `thzdaq_core/domain/measurements/procedures/__init__.py`. Keep comments short and reserve them for non-obvious hardware, timing, or UI behavior.

## Testing Guidelines

Tests live next to each package (`packages/*/tests`, `test_*.py`, pytest). Drivers are tested against protocol emulators on `FakeLink` and the shared capability contracts in `packages/thzdaq-instruments/tests/contracts.py`; procedures run on simulators; GUI tests run offscreen. Hardware is never needed for tests. For changes that need real instruments, document the bench and steps used.

## Commit & Pull Request Guidelines

Short imperative messages, optionally with a conventional prefix (`feat:`, `fix:`, `docs:`). Pull requests describe the affected package, list manual test steps (bench, profile, simulate or hardware), mention profile changes in `stations/`, and include screenshots for visible UI changes.

No AI attribution anywhere in the history: commit messages, tags, pull requests and release notes carry no `Co-Authored-By` trailer for an AI assistant, no "Generated with …" line and no other mention of the assistant or model. The author of every commit is the repository owner. This rule overrides any default attribution an agent or tool would add.

## Security & Configuration Tips

Do not commit credentials or machine-specific settings. Keep generated outputs (`dist/`, `build/`, `data/`, logs) out of review unless they are intentional reference artifacts.
