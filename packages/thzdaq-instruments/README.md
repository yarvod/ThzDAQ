# thzdaq-instruments

Instrument layer of ThzDAQ without any GUI dependency:

- `capabilities` — small interfaces by instrument ability (`Switchable`, `VoltageSource`,
  `FrequencySource`, `PowerDetector`, ...). Measurements depend on these, not on vendors.
- `transport` — message links (TCP socket, serial), Prologix GPIB addressing, a pool that shares
  one physical connection between instruments and serializes access with a lock.
- `instrument` — `Instrument`, `ScpiInstrument` and `Channel` base classes.
- `registry` — driver catalog: key → class, capabilities are derived from the class.
- `drivers` — Rigol DP832A, R&S HMP2030, Keithley 2200, Agilent E8247C, R&S NRX,
  Scontel SIS block, NI YIG (HTTP), Modbus chopper.
- `sim` — simulators for every capability, used for tests and running without hardware.

```python
from thzdaq_instruments import default_registry
from thzdaq_instruments.drivers import RigolDP832A

registry = default_registry()
supply = registry.open("rigol.dp832a", RigolDP832A.connection("169.254.0.14"))
if_switch = supply.channel(2)          # Switchable + VoltageSource + ...
if_switch.set_output(True)
supply.close()

sim = registry.open("rigol.dp832a", simulate=True)  # same shape, no hardware
```

Units: SI everywhere (Hz, V, A, K, s), power in dBm.

```bash
uv run --package thzdaq-instruments pytest packages/thzdaq-instruments
```
