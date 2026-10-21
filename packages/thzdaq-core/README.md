# thzdaq-core

Bench model, measurements and data of ThzDAQ without any GUI dependency.

## Station (bench profile)

A YAML profile lists instruments (driver + connection) and the **roles**
measurements use. A role is a part of an instrument, optionally wrapped by a
port adapter:

```yaml
roles:
  lo:          {instrument: lo_generator, adapter: scaled_frequency, options: {multiplier: 18}}
  if_selector: {instrument: if_switch_supply, channel: 2, adapter: sideband_selector}
  sis1:        {instrument: sis_block, channel: DEV4, attributes: {offset_voltage: 3.3e-5}}
  coil1:       {instrument: sis_block, channel: DEV3, accessor: ctrl}
```

```python
from thzdaq_instruments.capabilities import FrequencySource, PowerDetector
from thzdaq_core.station import Station

with Station.load("stations/2sb.example.yaml", simulate=True) as station:
    ports = station.require({"lo": FrequencySource, "detector": PowerDetector})
    ports["lo"].set_frequency(223e9)  # generator gets 223 GHz / 18
```

Adapters: `switch` (optionally inverted), `scaled_frequency`, `sideband_selector`;
add more with `register_adapter()`.

## CLI

```bash
uv run --isolated --package thzdaq-core thzdaq-station show stations/2sb.example.yaml
uv run --isolated --package thzdaq-core thzdaq-station check stations/2sb.example.yaml --simulate
```

`import-legacy` reads the QVariant-encoded `[Configs]` of the old app and needs PySide6
(`uv run --with` layers it, but only for `python -m`, not for console scripts):

```bash
uv run --isolated --package thzdaq-core --with pyside6==6.8.2.1 \
    python -m thzdaq_core.station.cli import-legacy settings.ini --name lab -o stations/lab.yaml
```

## Measurements

```python
from thzdaq_core.data import DataStore
from thzdaq_core.measurements import MeasurementRunner
from thzdaq_core.measurements.procedures import IVCurve
from thzdaq_core.station import Station

with Station.load("stations/2sb.example.yaml", simulate=True) as station:
    runner = MeasurementRunner(station, DataStore("data"))
    dataset = runner.run(IVCurve(voltage=(0, 7e-3, 351)), roles={"bias": "sis1"})
    print(dataset.status, len(dataset.records("iv")))
```

```bash
uv run --isolated --package thzdaq-core thzdaq list
uv run --isolated --package thzdaq-core thzdaq describe sis.iv_curve
uv run --isolated --package thzdaq-core thzdaq run sis.iv_curve \
    --station stations/2sb.example.yaml --simulate --role bias=sis1 --set voltage=0:7:351
```

Procedures: `sis.iv_curve`, `sis.pv_curve`, `sis.y_factor_voltage`, `sis.reflection`,
`sis.shot_noise`, `sis.demagnetize`, `monitor.time`, `grid.current_angle`, `if.hot_cold`,
`two_sb.if_balance`,
`two_sb.pump_balance`, `two_sb.srr`, `two_sb.tn`, `two_sb.optimization`
(`thzdaq describe <name>` for parameters and roles).

Also: `thzdaq_core.analysis.iv` (Rn, Rj, gap of an I-V curve) and `thzdaq_core.sis`
(calibration coefficients with safe expressions, demagnetization sequence).

Bench profiles accept numbers like `5e9` and `500.0e9` (YAML 1.2 style).

Datasets are JSON Lines under `data/<date>/`, written while the run goes;
`thzdaq show <file>` prints a summary, `read_dataset()` loads one in Python.
