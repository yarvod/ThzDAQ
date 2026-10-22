import json
import logging
import time
from typing import Dict, Optional

from thzdaq_instruments.errors import (
    ConfigurationError,
    InstrumentError,
    InstrumentResponseError,
)
from thzdaq_instruments.instrument import Channel, ScpiInstrument, SubdeviceType
from thzdaq_instruments.quantities import SHORT
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.transport.base import SOCKET, ConnectionSpec, Transport

logger = logging.getLogger(__name__)

DEVICES = ("DEV1", "DEV2", "DEV3", "DEV4")


class SisBiasChannel(Channel):
    """Voltage bias of one SIS device: VoltageSource + VoltageCurrentMeter.

    Offsets compensate the bias circuit: the instrument gets voltage - offset,
    readings come back + offset.
    """

    instrument: "ScontelSisBlock"
    quantities = (SHORT,)

    def __init__(self, instrument: "ScontelSisBlock", key: str):
        super().__init__(instrument, key)
        self.offset_voltage = 0.0
        self.offset_current = 0.0
        self._setpoint: Optional[float] = None

    def set_voltage(self, voltage: float) -> None:
        response = self.instrument.command(
            f"BIAS:{self.key}:VOLT {voltage - self.offset_voltage}"
        )
        if response != "OK":
            raise InstrumentResponseError(
                f"{self.name}: setting {voltage} V answered {response!r}"
            )
        self._setpoint = voltage

    def get_voltage(self) -> float:
        """Last programmed voltage; the block can't report its setpoint."""
        if self._setpoint is None:
            return self.read_voltage()
        return self._setpoint

    def read_voltage(self) -> float:
        return (
            self.instrument.command_float(f"BIAS:{self.key}:VOLT?")
            + self.offset_voltage
        )

    def read_current(self) -> float:
        return (
            self.instrument.command_float(f"BIAS:{self.key}:CURR?")
            + self.offset_current
        )

    def measure(self) -> ChannelReading:
        return ChannelReading(self.read_voltage(), self.read_current())

    def set_voltage_precise(
        self,
        voltage: float,
        tolerance: float = 1e-3,
        max_iterations: int = 30,
        settle_time: float = 1.0,
        abs_tolerance: float = 1e-6,
    ) -> float:
        """Correct the setpoint until the measured voltage is within tolerance.

        tolerance is relative, abs_tolerance (V) keeps it finite near 0 V.
        Returns the measured voltage, raises InstrumentError if it isn't reached.
        """
        allowed = max(tolerance * abs(voltage), abs_tolerance)
        target = voltage
        measured = self.read_voltage()
        for _ in range(max_iterations):
            if abs(measured - voltage) <= allowed:
                return measured
            self.set_voltage(target)
            time.sleep(settle_time)
            measured = self.read_voltage()
            target += voltage - measured
        if abs(measured - voltage) <= allowed:
            return measured
        raise InstrumentError(
            f"{self.name}: {voltage * 1e3:.3f} mV not reached in {max_iterations} "
            f"iterations, measured {measured * 1e3:.3f} mV"
        )

    def get_short(self) -> bool:
        return self.instrument.command(f"BIAS:{self.key}:SHOR?") == "1"

    def set_short(self, value: bool) -> None:
        self.instrument.command(f"BIAS:{self.key}:SHOR {1 if value else 0}")

    def get_resistance(self) -> float:
        """Equivalent resistance of the current measurement circuit, Ohm."""
        return self.instrument.command_float(f"BIAS:{self.key}:CMRE?")

    def get_data(self) -> str:
        return self.instrument.command(f"BIAS:{self.key}:DATA?")

    def write_calibration(self, coefficients: dict) -> str:
        """Store evaluated DAC/ADC coefficients in the device EEPROM."""
        payload = json.dumps(
            coefficients, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
        return self.instrument.command(f"BIAS:{self.key}:EEPR {payload}")


class SisCtrlChannel(Channel):
    """Magnetic field coil current of one device: CurrentSource."""

    instrument: "ScontelSisBlock"
    quantities = (SHORT,)

    def set_current(self, current: float) -> None:
        self.instrument.command(f"CTRL:{self.key}:CURR {current}")

    def get_current(self) -> float:
        return self.instrument.command_float(f"CTRL:{self.key}:CURR?")

    def get_short(self) -> bool:
        return self.instrument.command(f"CTRL:{self.key}:SHOR?") == "1"

    def set_short(self, value: bool) -> None:
        self.instrument.command(f"CTRL:{self.key}:SHOR {1 if value else 0}")

    def get_data(self) -> str:
        return self.instrument.command(f"CTRL:{self.key}:DATA?")


class ScontelSisBlock(ScpiInstrument):
    """Scontel SIS bias block. Bias channels via channel(dev), coil via ctrl(dev).

    The block answers "ERROR" now and then (~2% of requests), every command is
    retried. Its replies may come without a line terminator, so use the
    recommended connection (chunk reads with a short delay).
    """

    channel_class = SisBiasChannel
    channel_keys = DEVICES
    subdevices = {
        "sis_bias": SubdeviceType("SIS bias", "channel", DEVICES, SisBiasChannel),
        "sis_coil": SubdeviceType("SIS coil", "ctrl", DEVICES, SisCtrlChannel),
    }

    def __init__(
        self,
        transport: Transport,
        *,
        name: Optional[str] = None,
        attempts: int = 3,
        offsets: Optional[Dict[str, tuple]] = None,
    ):
        super().__init__(transport, name=name)
        self.attempts = attempts
        self._ctrl: Dict[str, SisCtrlChannel] = {}
        for device, (offset_voltage, offset_current) in (offsets or {}).items():
            bias = self.channel(device)
            bias.offset_voltage = offset_voltage
            bias.offset_current = offset_current

    @staticmethod
    def connection(host: str = "169.254.190.83", port: int = 9876) -> ConnectionSpec:
        return ConnectionSpec(
            SOCKET, host=host, port=port, read_termination=None, read_delay=0.05
        )

    def ctrl(self, device: str) -> SisCtrlChannel:
        if device not in DEVICES:
            raise ConfigurationError(f"{self.name} has no device {device!r}")
        if device not in self._ctrl:
            self._ctrl[device] = SisCtrlChannel(self, device)
        return self._ctrl[device]

    def command(self, command: str) -> str:
        last = ""
        for attempt in range(1, self.attempts + 1):
            try:
                last = self.query(command)
            except InstrumentError as e:
                logger.warning(f"[{self.name}] {command!r} attempt {attempt}: {e}")
                last = str(e)
                continue
            if "ERROR" not in last:
                return last
            logger.warning(f"[{self.name}] {command!r} attempt {attempt}: {last!r}")
        raise InstrumentResponseError(
            f"{self.name}: {command!r} failed after {self.attempts} attempts: {last!r}"
        )

    def command_float(self, command: str) -> float:
        for attempt in range(1, self.attempts + 1):
            response = self.command(command)
            try:
                return float(response)
            except ValueError:
                logger.warning(f"[{self.name}] {command!r} answered {response!r}")
        raise InstrumentResponseError(
            f"{self.name}: no number in answer to {command!r}"
        )

    def identify(self) -> str:
        return f"Scontel SIS block {self.name}"

    def test(self, device: str) -> bool:
        return self.command(f"GEN:{device}:STAT?") == "OK"
