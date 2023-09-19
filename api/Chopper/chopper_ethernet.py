import time

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


if __name__ == "__main__":
    chopper = ChopperEthernet()
    chopper.connect()
    chopper.path0()
    chopper.path0()
