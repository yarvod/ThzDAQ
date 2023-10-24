import time
from typing import Tuple

from pymodbus.client import ModbusTcpClient

from api.Chopper.chopper_sync import Chopper


class ChopperEthernet(Chopper):
    def __init__(
        self,
        host: str = "169.254.54.24",
        port: int = 1111,
        baudrate: int = 9600,
        slave_address: int = 1,
    ):
        super().__init__(host, port, baudrate, slave_address)

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

    def read_di23(self) -> Tuple[bool, bool]:
        results = self.client.read_holding_registers(
            int(0x0179), count=1, slave=self.slave_address
        ).registers
        num = next((result for result in results), None)
        bits_str = "{0:08b}".format(num)
        return bits_str[-2] == "1", bits_str[-3] == "1"


if __name__ == "__main__":
    chopper = ChopperEthernet()
    chopper.connect()
    print(chopper.read_di23())
    chopper.client.close()
