import logging

from pymodbus.client import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder

logger = logging.getLogger(__name__)


class HiCube:
    def __init__(
        self,
        host: str = "169.254.54.24",
        port: int = 1111,
        baudrate: int = 9600,
        slave_address: int = 1,
        *args,
        **kwargs,
    ):
        self.host = host
        self.port = port
        self.baudrate = baudrate
        self.slave_address = slave_address
        self.client = None
        self.init_client()

    def init_client(self):
        self.port = int(self.port)
        if self.client is not None:
            if self.client.connected:
                self.client.close()
        self.client = ModbusTcpClient(
            method="rtu",
            host=self.host,
            port=self.port,
            baudrate=self.baudrate,
            stopbits=1,
            bytesize=8,
            parity="N",
        )

    def connect(self) -> bool:
        if not self.client.connected:
            self.client.connect()
        logger.info(
            f"[{[self.__class__.__name__]}.connect] Connected {self.client.connected}"
        )
        return self.client.connected

    def close(self):
        self.client.close()
        logger.info(f"[{[self.__class__.__name__]}.close] Client closed")

    def __del__(self):
        logger.info(f"[{[self.__class__.__name__]}.__del__] Instance deleted")

    def motor_turbo_pump(self, value: int = 0):
        """Turn on/off motor turbo pump
        0 - off, 1 - on"""
        self.client.write_register(address=23, value=value, slave=self.slave_address)

    def pumping_station(self, value: int = 0):
        """Turn on/off pumping station
        0 - off, 1 - on"""
        self.client.write_register(address=10, value=value, slave=self.slave_address)

    def get_actual_speed(self) -> int:
        result = self.client.read_holding_registers(address=309, count=2, slave=123)
        if isinstance(result, Exception):
            raise result
        decoder = BinaryPayloadDecoder.fromRegisters(
            result.registers, byteorder=Endian.BIG, wordorder=Endian.BIG
        )
        actual_speed = decoder.decode_32bit_int()
        return actual_speed

    def get_pressure(self) -> int:
        result = self.client.read_holding_registers(
            address=340, count=1, slave=self.slave_address
        )
        if isinstance(result, Exception):
            raise result
        decoder = BinaryPayloadDecoder.fromRegisters(
            result.registers, byteorder=Endian.BIG, wordorder=Endian.BIG
        )
        actual_speed = decoder.decode_32bit_int()
        return actual_speed


if __name__ == "__main__":
    pump = HiCube(slave_address=2)
    pump.connect()
    print(pump.get_actual_speed())
