# thzdaq-core

The bench, its measurements and data, without GUI or network. Three layers; dependencies
point inward and import-linter checks them (root `pyproject.toml`):

- `domain/` — the station and its profile format, device kinds and ports, procedures with
  their parameters and plots, the measurement, analysis, SIS tools. No files, clocks or
  threads of its own.
- `application/` — use cases that drive the domain: the measurement runner (threads,
  autosave, time stamps) and the ports it needs (`ports.py`).
- `adapters/` — files: measurements as JSON (`json_store.py`), profiles as YAML
  (`yaml_profiles.py`), the old program's `settings.ini` (`legacy_profiles.py`).
- `cli/` — `thzdaq-station`: bench profiles as files, without the daemon.

The bench daemon (`thzdaq[daemon]`) runs it; clients reach it only through `thzdaq-api`
([docs/daemon.md](https://github.com/yarvod/ThzDAQ/blob/master/docs/daemon.md)).

## Station

A profile (YAML, version 2) lists instruments (driver, connection) and the devices
configured on them; ids name the kind of device (`stations/2sb.example.yaml`):

```python
from thzdaq_core.adapters.yaml_profiles import load_station
from thzdaq_core.domain.station.station import Station

with Station(load_station("stations/2sb.example.yaml"), simulate=True) as station:
    bias = station.device("sis_bias_1")
    bias.set_voltage(2.3e-3)
```

```bash
uv run thzdaq-station show stations/2sb.example.yaml
uv run thzdaq-station check stations/2sb.example.yaml --simulate
```

`import-legacy` reads the QVariant-encoded `[Configs]` of the old program and needs PySide6:

```bash
uv run python -m thzdaq_core.cli.station import-legacy settings.ini --name lab -o stations/lab.yaml
```

## Measurements

```python
from thzdaq_core.adapters.json_store import MeasurementStore
from thzdaq_core.adapters.yaml_profiles import load_station
from thzdaq_core.application.runner import MeasurementRunner
from thzdaq_core.domain.measurements.catalog import get_procedure
from thzdaq_core.domain.station.station import Station

with Station(load_station("stations/2sb.example.yaml"), simulate=True) as station:
    runner = MeasurementRunner(station, MeasurementStore("data"))
    procedure = get_procedure("sis.iv_curve")(voltage=(0, 7e-3, 351))
    measurement = runner.run(procedure, devices={"bias": "sis_bias_1"})
    print(measurement.status, len(measurement.records("iv")))
```

```bash
uv run thzdaq procedures
uv run thzdaq describe sis.iv_curve
uv run thzdaq --simulate run sis.iv_curve --device bias=sis_bias_1 --set voltage=0:7:351
uv run thzdaq show data/2026-10-29/000001_sis_iv_curve.json
```

Procedures are listed explicitly in `domain/measurements/procedures/__init__.py`
(`BUILTIN`); the catalog (`domain/measurements/catalog.py`) offers them by name.
Measurements are JSON files `data/<day>/<number>_<procedure>.json`, saved while the run
goes.
