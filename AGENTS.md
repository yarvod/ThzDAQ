# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python 3 desktop application for SIS mixer control and measurements. The entry point is `main.py`, which starts the PySide6 UI from `interface/index.py`. Hardware integrations live in `api/`, grouped by vendor or device type, while UI widgets and windows live under `interface/components/`, `interface/views/`, and `interface/windows/`. Runtime state and Qt models are in `store/`, background workers are in `threads/`, shared helpers are in `utils/`, and measurement scripts are in `measures/`. Static UI assets are in `assets/`. Project metadata and dependency pins are defined by `pyproject.toml` and `uv.lock`; `requirements/base.txt` is retained for legacy tooling.

## Build, Test, and Development Commands

- `uv sync --locked` creates or updates `.venv` from the committed lock file.
- `uv lock --check` verifies that `uv.lock` matches `pyproject.toml`; run `uv lock` after changing dependencies.
- `uv add <package>` and `uv remove <package>` are the standard ways to change Python dependencies.
- `uv run python main.py` runs the desktop application in the managed environment.
- `uv run build.bat [app_name]` builds a Windows PyInstaller distribution; the default name is `SIS_manager`.
- `sh build.sh` builds the Linux/macOS PyInstaller distribution.
- `uvx pre-commit run --all-files` runs formatting and hygiene hooks before committing.

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

All Python environment and command interactions must go through `uv`: use `uv sync`, `uv add`/`uv remove`, and `uv run ...`. Do not invoke `pip` directly or manually maintain a separate virtual environment. Keep `pyproject.toml` and `uv.lock` committed and synchronized.

## Coding Style & Naming Conventions

Use Python with 4-space indentation. Follow the existing module style: device APIs use clear vendor/device names such as `api/Rigol/DP832A.py`, UI classes use widget-oriented names such as `ChopperManagingGroup`, and shared state/models stay in `store/`. The configured formatter is Black, and pre-commit also runs autoflake to remove unused imports. Keep comments short and reserve them for non-obvious hardware, timing, or UI behavior.

## Testing Guidelines

There is no dedicated `tests/` suite yet. Treat scripts such as `api/Sumitomo/tests.py` and measurement modules in `measures/` as hardware-oriented checks, not general unit tests. When adding pure logic, prefer small unit tests in a new `tests/` directory using `test_*.py` naming. For UI or hardware changes, document the manual device or simulator scenario used and avoid requiring live hardware for import-time checks.

## Commit & Pull Request Guidelines

Recent history uses short imperative messages, sometimes with a conventional prefix such as `feat:`. Keep commits focused and use messages like `fix chopper status parsing` or `feat: add YIG calibration control`. Pull requests should describe the affected device/UI area, list manual test steps, mention any configuration or `.env` changes, and include screenshots for visible UI changes.

## Security & Configuration Tips

Do not commit local credentials or machine-specific settings. Use `example.env` as the template for `.env`, and keep generated outputs such as `dist/`, `build/`, `dumps/`, logs, and local measurement data out of review unless they are intentionally updated reference artifacts.
