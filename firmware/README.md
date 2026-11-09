# Firmware

`arduino_grid/grid_1`, `arduino_grid/grid_2` — Arduino sketches of the wire grid
rotators driven by `thzdaq_instruments.drivers.ArduinoGrid` (`arduino.grid`):
HTTP `POST /rotate {"angle": <relative degrees>}` and `POST /test`. Both build
with the IDE's own `Ethernet` library only (a W5500 on SPI, CS D10):

| Grid | Board | IP | FQBN |
| --- | --- | --- | --- |
| `grid_1` | Iskra Neo (ATmega32U4, Leonardo compatible) | 169.254.0.52 | `arduino:avr:leonardo` |
| `grid_2` | Arduino Nano (ATmega328P, old bootloader) | 169.254.0.53 | `arduino:avr:nano:cpu=atmega328old` |

```bash
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328old firmware/arduino_grid/grid_2
```

They also answer `GET /status` with `uptime_s`, `eth_restores` and `link`: after
a glitch, a small `uptime_s` means the board rebooted (its supply dipped), a
grown `eth_restores` that the W5500 lost its settings and the firmware wrote
them again. They log to Serial at 115200 (on the Iskra Neo, the USB port).

`grid_2` turns the stepper driver off between moves (`HOLD_WHEN_IDLE`), so the
motor carries no current while it is plugged in or out. `grid_1` has no ENABLE
line: its coils always carry the holding current.
