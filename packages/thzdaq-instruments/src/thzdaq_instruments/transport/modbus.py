import threading
from typing import List, Protocol, Sequence

from thzdaq_instruments.errors import (
    ConfigurationError,
    InstrumentConnectionError,
    InstrumentResponseError,
)
from thzdaq_instruments.transport.base import MODBUS_RTU, MODBUS_TCP, ConnectionSpec


class Registers(Protocol):
    """Holding registers of one Modbus slave."""

    def read(self, address: int, count: int = 1) -> List[int]:
        ...

    def write(self, address: int, value: int) -> None:
        ...

    def write_many(self, address: int, values: Sequence[int]) -> None:
        ...

    def close(self) -> None:
        ...


def int32_to_registers(value: int) -> List[int]:
    raw = value & 0xFFFFFFFF
    return [raw >> 16, raw & 0xFFFF]


def registers_to_int32(registers: Sequence[int]) -> int:
    raw = (registers[0] << 16) | registers[1]
    return raw - (1 << 32) if raw & 0x80000000 else raw


class PymodbusRegisters:
    """Registers over pymodbus TCP or RTU client, errors become InstrumentError."""

    def __init__(self, spec: ConnectionSpec, slave: int = 1):
        from pymodbus.client import ModbusSerialClient, ModbusTcpClient

        if spec.kind == MODBUS_TCP:
            self.client = ModbusTcpClient(
                host=spec.host, port=int(spec.port), timeout=spec.timeout
            )
        elif spec.kind == MODBUS_RTU:
            self.client = ModbusSerialClient(
                port=spec.serial_port,
                baudrate=spec.baudrate,
                stopbits=1,
                bytesize=8,
                parity="N",
                timeout=spec.timeout,
            )
        else:
            raise ConfigurationError(f"{spec.kind} is not a Modbus connection")
        self.slave = slave
        self.lock = threading.RLock()
        if not self.client.connect():
            raise InstrumentConnectionError(f"Modbus {spec.link_key} is not reachable")

    def _check(self, response, what: str):
        from pymodbus.exceptions import ModbusException

        if isinstance(response, ModbusException) or response.isError():
            raise InstrumentResponseError(f"Modbus {what}: {response}")
        return response

    def _call(self, what: str, func, *args, **kwargs):
        from pymodbus.exceptions import ConnectionException, ModbusException

        with self.lock:
            try:
                return self._check(func(*args, slave=self.slave, **kwargs), what)
            except (ConnectionException, OSError) as e:
                # A reset socket (WinError 10054) comes as a bare OSError
                raise InstrumentConnectionError(f"Modbus {what}: {e}") from e
            except ModbusException as e:
                raise InstrumentResponseError(f"Modbus {what}: {e}") from e

    def read(self, address: int, count: int = 1) -> List[int]:
        response = self._call(
            f"read {address:#06x}",
            self.client.read_holding_registers,
            address,
            count=count,
        )
        return list(response.registers)

    def write(self, address: int, value: int) -> None:
        self._call(f"write {address:#06x}", self.client.write_register, address, value)

    def write_many(self, address: int, values: Sequence[int]) -> None:
        self._call(
            f"write {address:#06x}", self.client.write_registers, address, list(values)
        )

    def close(self) -> None:
        with self.lock:
            self.client.close()
