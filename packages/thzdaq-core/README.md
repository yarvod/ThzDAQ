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
