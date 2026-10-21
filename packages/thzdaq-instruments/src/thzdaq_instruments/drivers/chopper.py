import logging
import threading
import time
from typing import Optional, Tuple

from thzdaq_instruments.errors import ConfigurationError, InstrumentError
from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.transport.base import MODBUS_TCP, ConnectionSpec
from thzdaq_instruments.transport.modbus import (
    PymodbusRegisters,
    Registers,
    int32_to_registers,
    registers_to_int32,
)

logger = logging.getLogger(__name__)

PULSES_PER_TURN = 10000
DETENT = 2500  # pulses between blade positions, 90 degrees
CW, CCW = 0, 1

# Stepper driver registers
REG_DIRECTION = 0x0007
REG_DIGITAL_INPUTS = 0x0179
REG_MOTION_STATUS = 0x1003
REG_COMMAND = 0x1801
REG_CONTROL = 0x6002
REG_QUICK_STOP_TIME = 0x6017
REG_POSITION = 0x602C
REG_PR0 = 0x6200  # relative move: mode, pos hi, pos lo, speed, acc, dec
REG_PR1_MODE = 0x6208
REG_PR1_SPEED = 0x620B
REG_PR1_ACC = 0x620C
REG_PR1_DEC = 0x620D
REG_PR2_MODE = 0x6218
REG_PR2_POSITION = 0x6219
REG_PR2_SPEED = 0x621B
REG_PR2_ACC = 0x621C
REG_PR2_DEC = 0x621D

CMD_SAVE_EEPROM = 0x2211
CTRL_TRIGGER_PR0 = 0x010
CTRL_TRIGGER_PR1 = 0x011
CTRL_TRIGGER_PR2 = 0x013
CTRL_SET_ORIGIN = 0x021
CTRL_EMERGENCY_STOP = 0x040

Sensors = Tuple[bool, bool]
HOT: Sensors = (True, True)
COLD: Sensors = (False, False)


class ModbusChopper(Instrument):
    """Chopper on a Modbus stepper driver with two load position sensors: LoadSwitch.

    Both sensors on = hot load in the beam, both off = cold load.
    """

    def __init__(
        self,
        connection: Optional[ConnectionSpec] = None,
        *,
        name: Optional[str] = None,
        slave: int = 1,
        registers: Optional[Registers] = None,
        move_wait: float = 0.3,
        align_wait: float = 1.0,
        step_wait: float = 0.1,
        align_steps: int = 20,
        speed: int = 25,  # rpm for step moves
    ):
        super().__init__(name=name)
        if registers is None:
            registers = PymodbusRegisters(connection or self.connection(), slave)
        self.registers = registers
        self.move_wait = move_wait
        self.align_wait = align_wait
        self.step_wait = step_wait
        self.align_steps = align_steps
        self.speed = speed
        self.frequency = 1.0  # Hz, continuous rotation
        self._lock = threading.RLock()

    @staticmethod
    def connection(host: str = "169.254.54.24", port: int = 1111) -> ConnectionSpec:
        return ConnectionSpec(MODBUS_TCP, host=host, port=port)

    def identify(self) -> str:
        return f"Modbus chopper {self.name}"

    def close(self) -> None:
        self.registers.close()

    # Low level
    def set_direction(self, direction: int) -> None:
        """0 - CW, 1 - CCW"""
        self.registers.write(REG_DIRECTION, direction)

    def set_origin(self) -> None:
        self.registers.write(REG_CONTROL, CTRL_SET_ORIGIN)

    def position(self) -> int:
        """Pulses, PULSES_PER_TURN per turn"""
        return registers_to_int32(self.registers.read(REG_POSITION, 2))

    def motion_status(self) -> int:
        return self.registers.read(REG_MOTION_STATUS)[0]

    def is_running(self) -> bool:
        return bool(self.motion_status() & 0b100)

    def read_sensors(self) -> Sensors:
        """(left DI2, right DI3), True - sensor sees the hot load."""
        bits = self.registers.read(REG_DIGITAL_INPUTS)[0]
        return bool(bits & 0b10), bool(bits & 0b100)

    def emergency_stop(self) -> None:
        self.registers.write(REG_CONTROL, CTRL_EMERGENCY_STOP)

    def save_to_eeprom(self) -> None:
        self.registers.write(REG_COMMAND, CMD_SAVE_EEPROM)

    # Moves
    def rotate(self, angle: float = 90, slow: bool = False, align: bool = True) -> None:
        """Relative move by angle, degrees, in the current direction."""
        pulses = int(angle / 360 * PULSES_PER_TURN)
        if not 0 < pulses <= 0xFFFF:
            raise ConfigurationError(f"Rotation by {angle} degrees is not supported")
        acc = 10000 if slow else 5000
        with self._lock:
            self.registers.write_many(
                REG_PR0, [0b01000001, 0, pulses, self.speed, acc, 10000]
            )
            if not slow and align:
                position = self.position()
                if abs(position - round(position / DETENT) * DETENT) > 50:
                    self.align()
                    time.sleep(self.move_wait)
            self.registers.write(REG_CONTROL, CTRL_TRIGGER_PR0)
            time.sleep(self.move_wait)

    def go_to_position(
        self, pulses: int, speed: int = 25, acc_time: int = 3000, dec_time: int = 3000
    ) -> None:
        with self._lock:
            self.registers.write_many(REG_PR2_POSITION, int32_to_registers(pulses))
            self.registers.write(REG_PR2_MODE, 0b00000001)  # absolute
            self.registers.write(REG_PR2_SPEED, speed)
            self.registers.write(REG_PR2_ACC, acc_time)
            self.registers.write(REG_PR2_DEC, dec_time)
            self.registers.write(REG_CONTROL, CTRL_TRIGGER_PR2)
            time.sleep(self.move_wait)

    def align(self) -> None:
        """Snap to the nearest blade detent."""
        with self._lock:
            position = self.position()
            target = round(position / DETENT) * DETENT
            if abs(target - position) > 50:
                self.go_to_position(target)

    def set_frequency(self, frequency: float) -> None:
        """Chopping frequency for continuous rotation, Hz."""
        self.frequency = frequency
        self.registers.write(REG_PR1_SPEED, int(frequency * 60))

    def start_rotation(
        self, frequency: Optional[float] = None, acc_time: int = 20000
    ) -> None:
        with self._lock:
            self.registers.write(REG_PR1_MODE, 0b0010)  # velocity mode
            self.set_frequency(self.frequency if frequency is None else frequency)
            self.registers.write(REG_PR1_ACC, acc_time)
            self.registers.write(REG_PR1_DEC, acc_time)
            self.registers.write(REG_CONTROL, CTRL_TRIGGER_PR1)

    def stop(self, stop_time: int = 10000, timeout: Optional[float] = None) -> None:
        """Decelerate to a stop within stop_time ms and wait for it."""
        with self._lock:
            self.registers.write(REG_QUICK_STOP_TIME, stop_time)
            self.emergency_stop()
            deadline = time.monotonic() + (
                timeout if timeout is not None else stop_time / 1000 + 5
            )
            while self.is_running():
                if time.monotonic() > deadline:
                    raise InstrumentError(f"{self.name}: didn't stop in time")
                time.sleep(self.step_wait)

    # LoadSwitch
    def to_hot(self) -> None:
        self._align_to(HOT)

    def to_cold(self) -> None:
        self._align_to(COLD)

    def _align_to(self, target: Sensors) -> None:
        opposite = COLD if target == HOT else HOT
        hot = target == HOT
        with self._lock:
            sensors = self.read_sensors()
            for _ in range(self.align_steps):
                if sensors == target:
                    break
                if sensors == opposite:
                    self.rotate(90, slow=True)
                    time.sleep(self.align_wait)
                else:
                    left_on = sensors[0]
                    # Blade half way: nudge towards the target
                    if hot:
                        self.set_direction(CCW if left_on else CW)
                    else:
                        self.set_direction(CW if left_on else CCW)
                    self.rotate(10, slow=True)
                    time.sleep(self.step_wait)
                sensors = self.read_sensors()
            else:
                if sensors != target:
                    raise InstrumentError(
                        f"{self.name}: {'hot' if hot else 'cold'} load not reached, "
                        f"sensors {sensors}"
                    )
            self.set_direction(CW)
            self.set_origin()
