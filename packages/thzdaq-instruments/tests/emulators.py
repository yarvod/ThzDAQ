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


class ZvaEmulator(ScpiEmulator):
    def __init__(self, zeros_before: int = 0):
        super().__init__()
        self.points, self.start, self.stop = 11, 2e9, 12e9
        self.power = -30.0
        self.data_format = "COMP"
        self.zeros_before = zeros_before
        self.parameters = {"Trc1": "S11"}

        def define(_channel, trace, parameter):
            self.parameters = {trace: parameter}

        self.route(
            r"\*IDN\?", lambda: "Rohde&Schwarz,ZVA67-4Port,1145111052100151,3.60"
        )
        self.route(r"SWE:POIN (\d+)", lambda v: setattr(self, "points", int(v)))
        self.route(r"SWE:POIN\?", lambda: str(self.points))
        self.route(r"SENS:FREQ:STAR (\S+)", lambda v: setattr(self, "start", float(v)))
        self.route(r"SENS:FREQ:STOP (\S+)", lambda v: setattr(self, "stop", float(v)))
        self.route(r"SENS:FREQ:STAR\?", lambda: f"{self.start}")
        self.route(r"SENS:FREQ:STOP\?", lambda: f"{self.stop}")
        self.route(r"SOUR:POW (\S+)", lambda v: setattr(self, "power", float(v)))
        self.route(r"SOUR:POW\?", lambda: f"{self.power}")
        self.route(r"SENS(\d):AVER (ON|OFF)", lambda c, v: None)
        self.route(r"SENS(\d):AVER:COUN (\d+)", lambda c, v: None)
        self.route(r"CALC:FORM (\w+)", lambda v: setattr(self, "data_format", v))
        self.route(r"CALC:FORM\?", lambda: self.data_format)
        self.route(r"CALC(\d):PAR:DEF (\w+),(\w+)", define)
        self.route(
            r"CALC(\d):PAR:CAT\?",
            lambda c: ",".join(f"'{t},{p}" + "'" for t, p in self.parameters.items()),
        )
        self.route(r"CALC(\d):DATA\? FDAT", self._data)

    def _data(self, _channel):
        if self.zeros_before > 0:
            self.zeros_before -= 1
            return ",".join(["0"] * (2 * self.points))
        return ",".join(f"{0.1 * i},{-0.05 * i}" for i in range(self.points))


class FsekEmulator(ScpiEmulator):
    def __init__(self, tone: float = 5.0001e9, level: float = -42.5):
        super().__init__()
        self.center, self.span = 5e9, 1e6
        self.tone, self.level = tone, level
        self.rbw = self.vbw = None
        self.continuous = True
        self.marker = (0.0, -100.0)

        def set_start(v):
            stop = self.center + self.span / 2
            self.center, self.span = (float(v) + stop) / 2, stop - float(v)

        def set_stop(v):
            start = self.center - self.span / 2
            self.center, self.span = (start + float(v)) / 2, float(v) - start

        self.route(r"\*IDN\?", lambda: "Rohde&Schwarz,FSEK 30,834157/005,3.40")
        self.route(r":FREQ:CENT (\S+)Hz", lambda v: setattr(self, "center", float(v)))
        self.route(r":FREQ:CENT\?", lambda: f"{self.center}")
        self.route(r":FREQ:SPAN (\S+)Hz", lambda v: setattr(self, "span", float(v)))
        self.route(r":FREQ:SPAN\?", lambda: f"{self.span}")
        self.route(r":FREQ:STAR (\S+)Hz", set_start)
        self.route(r":FREQ:STOP (\S+)Hz", set_stop)
        self.route(r":FREQ:STAR\?", lambda: f"{self.center - self.span / 2}")
        self.route(r":FREQ:STOP\?", lambda: f"{self.center + self.span / 2}")
        self.route(r":BAND:RES (\S+)Hz", lambda v: setattr(self, "rbw", float(v)))
        self.route(r":BAND:VID (\S+)Hz", lambda v: setattr(self, "vbw", float(v)))
        self.route(r":BAND:VID:AUTO (ON|OFF)", lambda v: None)
        self.route(r"AVER:TYPE (\w+)", lambda v: None)
        self.route(
            r":INIT:CONT (ON|OFF)", lambda v: setattr(self, "continuous", v == "ON")
        )
        self.route(r":INIT:CONT\?", lambda: "1" if self.continuous else "0")
        self.route(r":INIT", lambda: None)
        self.route(
            r"CALC:MARK:MAX", lambda: setattr(self, "marker", (self.tone, self.level))
        )
        self.route(r"CALC:MARK:X\?", lambda: f"{self.marker[0]}")
        self.route(r"CALC:MARK:Y\?", lambda: f"{self.marker[1]}")
        self.route(r":TRAC:DATA\? (\w+)", lambda t: "-90,-80,garbage,-42.5,-90")


class LakeShoreEmulator(ScpiEmulator):
    def __init__(self):
        super().__init__()
        self.temperatures = {"A": 4.215, "B": 41.7, "C": 77.3, "D": 295.0}
        self.setpoints = {1: 0.0, 2: 0.0}
        self.ranges = {1: 0, 2: 0}
        self.manual = {1: 0.0, 2: 0.0}
        self.heater_setup = {1: "1,2,0.000,1", 2: "1,2,0.000,1"}
        self.out_mode = {1: "1,1,0", 2: "0,0,0"}
        self.mode = 1

        def store(target):
            def setter(output, value):
                target[int(output)] = type(target[int(output)])(value)

            return setter

        self.route(r"\*IDN\?", lambda: "LSCI,MODEL336,LSA2CMQ/LSA2C8R,2.9")
        self.route(r"KRDG\? ([A-D])", lambda k: f"+{self.temperatures[k]:.3f}")
        self.route(r"SRDG\? ([A-D])", lambda k: "+1234.5")
        self.route(r"SETP (\d),(\S+)", store(self.setpoints))
        self.route(r"SETP\? (\d)", lambda o: f"+{self.setpoints[int(o)]:.3f}")
        self.route(r"RANGE (\d),(\d)", store(self.ranges))
        self.route(r"RANGE\? (\d)", lambda o: str(self.ranges[int(o)]))
        self.route(r"MOUT (\d),(\S+)", store(self.manual))
        self.route(r"MOUT\? (\d)", lambda o: f"+{self.manual[int(o)]:.2f}")
        self.route(r"HTR\? (\d)", lambda o: "+012.5")
        self.route(r"HTRST\? (\d)", lambda o: "0")
        self.route(
            r"HTRSET (\d),(\S+)", lambda o, v: self.heater_setup.__setitem__(int(o), v)
        )
        self.route(r"HTRSET\? (\d)", lambda o: self.heater_setup[int(o)])
        self.route(
            r"OUTMODE (\d),(\S+)", lambda o, v: self.out_mode.__setitem__(int(o), v)
        )
        self.route(r"OUTMODE\? (\d)", lambda o: self.out_mode[int(o)])
        self.route(r"MODE ([0-2])", lambda v: setattr(self, "mode", int(v)))
        self.route(r"MODE\?", lambda: str(self.mode))


class Sr830Emulator(ScpiEmulator):
    def __init__(self):
        super().__init__()
        self.state = {"FREQ": 1000.0, "PHAS": 0.0, "SLVL": 0.1, "OFLT": 10, "SENS": 22}
        self.route(
            r"\*IDN\?", lambda: "Stanford_Research_Systems,SR830,s/n00000,ver1.07"
        )
        self.route(
            r"OUTP\? ([1-4])",
            lambda i: ["", "1.0E-3", "-2.0E-3", "2.236E-3", "-63.43"][int(i)],
        )
        self.route(r"SNAP\? 1,2", lambda: "1.0E-3,-2.0E-3")
        for key in ("FREQ", "PHAS", "SLVL", "OFLT", "SENS"):
            self.route(
                rf"{key} (\S+)", lambda v, k=key: self.state.__setitem__(k, float(v))
            )
            self.route(rf"{key}\?", lambda k=key: f"{self.state[k]:g}")
        self.route(r"AGAN", lambda: None)
        self.route(r"APHS", lambda: None)


class F70Emulator:
    """F-70 RS-232 protocol with CRC-16/MODBUS on every frame."""

    def __init__(self):
        from thzdaq_instruments.drivers.sumitomo import crc16_modbus

        self.crc = crc16_modbus
        self.running = False
        self.errors: List[str] = []

    def transport(self):
        link = FakeLink(self)
        link.open()
        return MessageTransport(link), link

    def _frame(self, fields):
        head = ",".join(fields) + ","
        return head + self.crc(head)

    def __call__(self, line):
        command, checksum = line[:4], line[4:]
        if self.crc(command) != checksum:
            self.errors.append(line)
            return "$???,3A5E"
        if command == "$TEA":
            return self._frame(
                ["$TEA", "068" if self.running else "022", "034", "032", "000"]
            )
        if command == "$PRA":
            return self._frame(["$PRA", "280" if self.running else "230", "000"])
        if command == "$STA":
            return self._frame(["$STA", "0301" if self.running else "0000"])
        if command in ("$ON1", "$OFF", "$RS1", "$CHR", "$CHP", "$POF"):
            self.running = {"$ON1": True, "$OFF": False}.get(command, self.running)
            return line
        self.errors.append(line)
        return None


class PfeifferBus:
    """Devices on one RS-485 line: {address: {parameter: raw data}}."""

    def __init__(self, devices):
        from thzdaq_instruments.drivers.pfeiffer import checksum

        self.checksum = checksum
        self.devices = devices
        self.errors: List[str] = []

    def __call__(self, line):
        body, check = line[:-3], line[-3:]
        if self.checksum(body) != check:
            self.errors.append(line)
            return None
        address, action, number = int(body[:3]), body[3:5], int(body[5:8])
        if address not in self.devices:
            return None  # nobody answers on the bus
        params = self.devices[address]
        data = body[10:]
        if action == "00":
            data = params.get(number, "NO_DEF")
        elif number in params:
            params[number] = data
        else:
            data = "NO_DEF"
        reply = f"{address:03d}10{number:03d}{len(data):02d}{data}"
        return reply + self.checksum(reply)
