# thzdaq-instruments

Instrument layer of ThzDAQ without any GUI dependency:

- `capabilities` — small interfaces by instrument ability (`Switchable`, `VoltageSource`,
  `FrequencySource`, `PowerDetector`, ...). Measurements depend on these, not on vendors.
- `transport` — message links (TCP socket, serial), Prologix GPIB addressing, a pool that shares
  one physical connection between instruments and serializes access with a lock.
- `instrument` — `Instrument`, `ScpiInstrument` and `Channel` base classes.
- `registry` — driver catalog: key → class, capabilities are derived from the class.
- `sim` — simulators for every capability, used for tests and running without hardware.

Units: SI everywhere (Hz, V, A, K, s), power in dBm.

```bash
uv run --package thzdaq-instruments pytest packages/thzdaq-instruments
```
