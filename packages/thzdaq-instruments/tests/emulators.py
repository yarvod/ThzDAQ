"""Stateful SCPI emulators of the lab instruments for FakeLink.

Each emulator answers like the device and records commands it doesn't know
in `errors`, so tests catch misspelled headers.
"""

import re
from typing import Callable, List, Optional, Tuple

from thzdaq_instruments.transport.base import MessageTransport
from thzdaq_instruments.transport.fake import FakeLink
from thzdaq_instruments.units import dbm_to_watt


class ScpiEmulator:
    def __init__(self):
        self.errors: List[str] = []
        self._routes: List[Tuple[re.Pattern, Callable]] = []

    def route(self, pattern: str, handler: Callable[..., Optional[str]]):
        self._routes.append((re.compile(pattern), handler))

    def __call__(self, command: str) -> Optional[str]:
        for pattern, handler in self._routes:
            match = pattern.fullmatch(command)
            if match:
                return handler(*match.groups())
        self.errors.append(command)
        return None

    def transport(self) -> Tuple[MessageTransport, FakeLink]:
        link = FakeLink(self)
        link.open()
        return MessageTransport(link), link


class SupplyState:
    def __init__(self, load: float = 100.0):
        self.output = False
        self.voltage = 0.0
        self.current = 1.0
        self.load = load

    def reading(self) -> Tuple[float, float]:
        if not self.output:
            return 0.0, 0.0
        return self.voltage, min(self.voltage / self.load, self.current)


class RigolEmulator(ScpiEmulator):
    def __init__(self):
        super().__init__()
        self.channels = {ch: SupplyState() for ch in (1, 2, 3)}
        ch = self.channels
        self.route(r"\*IDN\?", lambda: "RIGOL TECHNOLOGIES,DP832A,DP8A0000,00.01.14")
        self.route(r"\*TST\?", lambda: "TopBoard:PASS,BottomBoard:PASS,Fan:PASS")
        self.route(
            r":OUTP CH(\d),(ON|OFF)",
            lambda c, v: setattr(ch[int(c)], "output", v == "ON"),
        )
        self.route(r":OUTP\? CH(\d)", lambda c: "ON" if ch[int(c)].output else "OFF")
        self.route(
            r":SOURce(\d):VOLTage (\S+)",
            lambda c, v: setattr(ch[int(c)], "voltage", float(v)),
        )
        self.route(r":SOURce(\d):VOLTage\?", lambda c: f"{ch[int(c)].voltage:.3f}")
        self.route(
            r":SOURce(\d):CURRent (\S+)",
            lambda c, v: setattr(ch[int(c)], "current", float(v)),
        )
        self.route(r":SOURce(\d):CURRent\?", lambda c: f"{ch[int(c)].current:.4f}")
        self.route(r":MEAS:ALL\? CH(\d)", self._measure)

    def _measure(self, channel):
        voltage, current = self.channels[int(channel)].reading()
        return f"{voltage:.3f},{current:.4f},{voltage * current:.3f}"


class HmpEmulator(ScpiEmulator):
    def __init__(self):
        super().__init__()
        self.channels = {ch: SupplyState() for ch in (1, 2, 3)}
        self.selected = 1
        self.general = False

        def select(c):
            self.selected = int(c)

        def state():
            return self.channels[self.selected]

        self.route(r"\*IDN\?", lambda: "HAMEG,HMP2030,000000000,HW50020001/SW2.51")
        self.route(r"\*TST\?", lambda: "0")
        self.route(r"INST:NSEL (\d)", select)
        self.route(r"OUTP:GEN ([01])", lambda v: setattr(self, "general", v == "1"))
        self.route(r"OUTP:GEN\?", lambda: "1" if self.general else "0")
        self.route(r"OUTP:STAT ([01])", lambda v: setattr(state(), "output", v == "1"))
        self.route(r"OUTP:STAT\?", lambda: "1" if state().output else "0")
        self.route(
            r"SOUR:VOLT:LEV:AMPL (\S+)", lambda v: setattr(state(), "voltage", float(v))
        )
        self.route(r"SOUR:VOLT:LEV:AMPL\?", lambda: f"{state().voltage:.3f}")
        self.route(
            r"SOUR:CURR:LEV:AMPL (\S+)", lambda v: setattr(state(), "current", float(v))
        )
        self.route(r"SOUR:CURR:LEV:AMPL\?", lambda: f"{state().current:.4f}")
        self.route(r"MEAS:SCAL:VOLT\?", lambda: f"{state().reading()[0]:.3f}")
        self.route(r"MEAS:SCAL:CURR\?", lambda: f"{state().reading()[1]:.4f}")


class KeithleyEmulator(ScpiEmulator):
    def __init__(self):
        super().__init__()
        self.state = SupplyState()
        s = self.state
        self.route(r"\*IDN\?", lambda: "Keithley instruments,2200-30-5,0,1.0")
        self.route(r"\*TST\?", lambda: "0")
        self.route(r"OUTPUT ([01])", lambda v: setattr(s, "output", v == "1"))
        self.route(r"OUTPUT\?", lambda: "1" if s.output else "0")
        self.route(r"SOUR:VOLT (\S+)V", lambda v: setattr(s, "voltage", float(v)))
        self.route(r"SOUR:VOLT\?", lambda: f"{s.voltage}")
        self.route(r"SOUR:CURR (\S+)A", lambda v: setattr(s, "current", float(v)))
        self.route(r"SOUR:CURR\?", lambda: f"{s.current}")
        self.route(r"MEAS:VOLT\?", lambda: f"{s.reading()[0]}")
        self.route(r"MEAS:CURR\?", lambda: f"{s.reading()[1]}")


class AgilentEmulator(ScpiEmulator):
    def __init__(self):
        super().__init__()
        self.output = False
        self.frequency = 1e9
        self.power = -20.0
        self.attenuation = 0.0
        self.alc = 0.0
        self.multiplier = 1.0
        self.route(
            r"\*IDN\?", lambda: "Agilent Technologies, E8247C, US00000000, C.06.20"
        )
        self.route(r"OUTP ([01])", lambda v: setattr(self, "output", v == "1"))
        self.route(r"OUTP\?", lambda: "1" if self.output else "0")
        self.route(r":FREQ:FIX (\S+)", lambda v: setattr(self, "frequency", float(v)))
        self.route(r":FREQ:FIX\?", lambda: f"{self.frequency:+.11E}")
        self.route(r":FREQ:MULT (\S+)", lambda v: setattr(self, "multiplier", float(v)))
        self.route(r":FREQ:MULT\?", lambda: f"{self.multiplier:+.8E}")
        self.route(r"POW (\S+)dBm", lambda v: setattr(self, "power", float(v)))
        self.route(r"POW\?", lambda: f"{self.power:+.8E}")
        self.route(r":POW:ATT (\S+)", lambda v: setattr(self, "attenuation", float(v)))
        self.route(r":POW:ATT\?", lambda: f"{self.attenuation:+.8E}")
        self.route(r":POW:ALC:LEV (\S+)", lambda v: setattr(self, "alc", float(v)))
        self.route(r":POW:ALC:LEV\?", lambda: f"{self.alc:+.8E}")


class NrxEmulator(ScpiEmulator):
    def __init__(self, power_dbm: float = -30.0):
        super().__init__()
        self.power_dbm = power_dbm
        self.unit = "DBM"
        self.aperture = None
        self.averaging = None
        self.route(r"\*IDN\?", lambda: "ROHDE&SCHWARZ,NRX,000000,02.50")
        self.route(r"UNIT1:POW (DBM|W|DBUV)", lambda u: setattr(self, "unit", u))
        self.route(r"UNIT1:POW\?", lambda: self.unit)
        self.route(r"CALC:APER (\S+)", lambda v: setattr(self, "aperture", float(v)))
        self.route(
            r"CALC:CHAN:AVER:STAT ([01])",
            lambda v: setattr(self, "averaging", v == "1"),
        )
        self.route(r"READ\?", self._read)
        self.route(r"FETCH\?", self._read)

    def _read(self):
        if self.unit == "W":
            return f"{dbm_to_watt(self.power_dbm):.6E}"
        if self.unit == "DBUV":
            return f"{self.power_dbm + 107:.3f}"
        return f"{self.power_dbm:.3f}"


class SisEmulator(ScpiEmulator):
    """Bias source with gain error and offset; `fail` makes the next N answers ERROR."""

    def __init__(self, gain: float = 1.0, offset: float = 0.0):
        super().__init__()
        self.gain = gain
        self.offset = offset
        self.fail = 0
        self.setpoints = {dev: 0.0 for dev in ("DEV1", "DEV2", "DEV3", "DEV4")}
        self.ctrl = {dev: 0.0 for dev in self.setpoints}
        self.shorts = {
            f"{kind}:{dev}": "1" for kind in ("BIAS", "CTRL") for dev in self.setpoints
        }

        def set_bias(dev, value):
            self.setpoints[dev] = float(value)
            return "OK"

        def set_ctrl(dev, value):
            self.ctrl[dev] = float(value)
            return "OK"

        def set_short(kind, dev, value):
            self.shorts[f"{kind}:{dev}"] = value
            return "OK"

        self.route(r"BIAS:(DEV\d):VOLT (\S+)", set_bias)
        self.route(r"BIAS:(DEV\d):VOLT\?", lambda d: f"{self.actual(d)}")
        self.route(r"BIAS:(DEV\d):CURR\?", lambda d: f"{self.actual(d) / 20}")
        self.route(r"BIAS:(DEV\d):CMRE\?", lambda d: "100")
        self.route(r"CTRL:(DEV\d):CURR (\S+)", set_ctrl)
        self.route(r"CTRL:(DEV\d):CURR\?", lambda d: f"{self.ctrl[d]}")
        self.route(r"(BIAS|CTRL):(DEV\d):SHOR ([01])", set_short)
        self.route(r"(BIAS|CTRL):(DEV\d):SHOR\?", lambda k, d: self.shorts[f"{k}:{d}"])
        self.route(r"GEN:(DEV\d):STAT\?", lambda d: "OK")

    def actual(self, dev: str) -> float:
        return self.setpoints[dev] * self.gain + self.offset

    def __call__(self, command: str) -> Optional[str]:
        reply = super().__call__(command)
        if reply is not None and self.fail > 0:
            self.fail -= 1
            return "ERROR"
        return reply


class FakeJsonClient:
    """NI YIG REST service: echoes the written code as the result."""

    def __init__(self, result_offset: int = 0):
        self.result_offset = result_offset
        self.requests: List[Tuple[str, str, Optional[dict]]] = []
        self.closed = False

    def get(self, path):
        self.requests.append(("GET", path, None))
        return {}

    def post(self, path, data=None):
        self.requests.append(("POST", path, data))
        if data and "value" in data:
            return {"result": data["value"] + self.result_offset}
        return {}

    def close(self):
        self.closed = True


class MotorRegisters:
    """Stepper driver with a two-blade chopper and two load sensors.

    Hot load faces the beam around physical positions 0, 5000, ... pulses.
    The left sensor looks at position - delta, the right one at + delta.
    """

    def __init__(self, physical: int = 0, delta: int = 1000, stuck: bool = False):
        from thzdaq_instruments.drivers import chopper as c

        self.c = c
        self.values = {}
        self.physical = physical
        self.origin = 0
        self.delta = delta
        self.stuck = stuck
        self.writes: List[Tuple[int, object]] = []
        self.closed = False

    @staticmethod
    def hot(position: int) -> bool:
        return (position + 1250) % 5000 < 2500

    def sensors(self) -> Tuple[bool, bool]:
        return self.hot(self.physical - self.delta), self.hot(
            self.physical + self.delta
        )

    def read(self, address, count=1):
        c = self.c
        if address == c.REG_POSITION:
            return c.int32_to_registers(self.physical - self.origin)
        if address == c.REG_DIGITAL_INPUTS:
            left, right = self.sensors()
            return [(int(left) << 1) | (int(right) << 2)]
        if address == c.REG_MOTION_STATUS:
            return [0]
        return [self.values.get(address + i, 0) for i in range(count)]

    def write(self, address, value):
        c = self.c
        self.writes.append((address, value))
        self.values[address] = value
        if address != c.REG_CONTROL or self.stuck:
            if address == c.REG_CONTROL and value == c.CTRL_SET_ORIGIN:
                self.origin = self.physical
            return
        if value == c.CTRL_TRIGGER_PR0:
            sign = 1 if self.values.get(c.REG_DIRECTION, 0) == c.CW else -1
            self.physical += sign * self.values[c.REG_PR0 + 2]
        elif value == c.CTRL_TRIGGER_PR2:
            target = c.registers_to_int32(
                [self.values[c.REG_PR2_POSITION], self.values[c.REG_PR2_POSITION + 1]]
            )
            self.physical = target + self.origin
        elif value == c.CTRL_SET_ORIGIN:
            self.origin = self.physical

    def write_many(self, address, values):
        self.writes.append((address, list(values)))
        for index, value in enumerate(values):
            self.values[address + index] = value

    def close(self):
        self.closed = True
