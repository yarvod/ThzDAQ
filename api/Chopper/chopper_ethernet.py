import logging
import time
from typing import Tuple, Union

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusIOException

from api.Chopper.chopper_sync import Chopper


logger = logging.getLogger(__name__)


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
            host=self.host,
            port=self.port,
        )

    def read_di23(self) -> Union[None, Tuple[bool, bool]]:
        """
        DI2 - left
        DI3 - right

        True - hot state
        False - cold state
        """
        response = self.client.read_holding_registers(
            int(0x0179), count=1, slave=self.slave_address
        )
        if isinstance(response, ModbusIOException):
            logger.error(f"{response}")
            return None
        num = next((result for result in response.registers), None)
        bits_str = "{0:08b}".format(num)
        return bits_str[-2] == "1", bits_str[-3] == "1"

    def align_to_hot(self):
        steps = 20
        step = 1
        di2, di3 = self.read_di23()
        if di2 is False and di3 is False:
            self.path0_slow(90)
            time.sleep(1)

        while not (di2 is True and di3 is True):
            logger.debug(f"[STEP {step}/{steps}] Start new step")
            if step >= steps:
                logger.debug(f"Break align to hot, {step} steps exceeded")
                break
            if di2 is True and di3 is False:
                logger.debug(
                    f"[STEP {step}/{steps}] Left D is Hot, Right D is Cold. \n Rotate 2 degree CW"
                )
                self.motor_direction(1)
                self.path0_slow(10)
                time.sleep(0.1)
                di2, di3 = self.read_di23()
            elif di2 is False and di3 is True:
                logger.debug(
                    f"[STEP {step}/{steps}] Left D is Cold, Right D is Hot. \n Rotate 2 degree CCW"
                )
                self.motor_direction(0)
                self.path0_slow(10)
                time.sleep(0.1)
                di2, di3 = self.read_di23()
            step += 1
        else:
            self.path0_slow(3)
        self.motor_direction(0)
        self.set_origin()
        # self.go_to_pos(0)

    def align_to_cold(self):
        steps = 20
        step = 1
        di2, di3 = self.read_di23()
        if di2 is True and di3 is True:
            self.path0_slow(90)
            time.sleep(1)

        while not (di2 is False and di3 is False):
            logger.debug(f"[STEP {step}/{steps}] Start new step")
            if step >= steps:
                logger.debug(f"Break align to cold, {step} steps exceeded")
                break
            if di2 is True and di3 is False:
                logger.debug(
                    f"[STEP {step}/{steps}] Left D is Hot, Right D is Cold. \n Rotate 2 degree CW"
                )
                self.motor_direction(0)
                self.path0_slow(10)
                time.sleep(0.1)
                di2, di3 = self.read_di23()
            elif di2 is False and di3 is True:
                logger.debug(
                    f"[STEP {step}/{steps}] Left D is Cold, Right D is Hot. \n Rotate 2 degree CCW"
                )
                self.motor_direction(1)
                self.path0_slow(10)
                time.sleep(0.1)
                di2, di3 = self.read_di23()
            step += 1
        else:
            self.path0_slow(3)
        self.motor_direction(0)
        self.set_origin()


if __name__ == "__main__":
    chopper = ChopperEthernet()
    chopper.connect()
    try:
        chopper.path0(100)
        time.sleep(2)
        # chopper.align_to_hot()
        # time.sleep(2)
        # chopper.path0(125)
        # time.sleep(2)
        chopper.align_to_hot()
    except KeyboardInterrupt:
        chopper.client.close()
