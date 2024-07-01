import socket
import time
from typing import Union

import settings
from store.state import state
from utils.classes import BaseInstrument
from utils.logger import logger


class SisBlock(BaseInstrument):
    """
    Scontel SIS block operation interface.
    """

    def __init__(
        self,
        host: str = state.BLOCK_ADDRESS,
        port: int = state.BLOCK_PORT,
        adapter: str = settings.SOCKET,
        bias_dev: str = state.BLOCK_BIAS_DEV,
        ctrl_dev: str = state.BLOCK_CTRL_DEV,
        **kwargs,
    ):
        super().__init__(host=host, gpib=0, adapter=adapter, port=port)
        self.bias_dev = bias_dev
        self.ctrl_dev = ctrl_dev

    def connect(self):
        ...

    def disconnect(self):
        if self.adapter:
            self.adapter.close()

    def manipulate(self, cmd: str) -> str:
        """
        Base method to send command to block.
        Parameters:
            cmd (str): SCPI string command
        Returns:
            result (str): Block answer
        """
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                self.adapter.write(cmd)
                time.sleep(0.05)
                result = self.adapter.read()
                logger.debug(
                    f"[Block.manipulate] Received result: {result}; attempt {attempt}"
                )
                if "ERROR" in result:
                    logger.error(
                        f"[Block.manipulate] Received Error result: {result}; attempt {attempt}"
                    )
                    continue
                return result
            except Exception as e:
                logger.error(f"[Block.manipulate] Exception: {e}; attempt {attempt}")
                continue
        return ""

    def get_ctrl_short_status(self, s: socket.socket = None):
        """
        Method to get Short status for CTRL.
        Shorted = 1
        Opened = 0
        """
        return self.manipulate(f"CTRL:{self.ctrl_dev}:SHOR?")

    def set_ctrl_short_status(self, status: str):
        """
        Method to set Short status for CTRL.
        Shorted = 1
        Opened = 0
        """
        return self.manipulate(f"CTRL:{self.ctrl_dev}:SHOR {status}")

    def get_bias_short_status(self):
        """
        Method to get Short status for BIAS.
        Shorted = 1
        Opened = 0
        """
        return self.manipulate(f"BIAS:{self.bias_dev}:SHOR?")

    def set_bias_short_status(self, status: str):
        """
        Method to set Short status for BIAS.
        Shorted = 1
        Opened = 0
        """
        return self.manipulate(f"BIAS:{self.bias_dev}:SHOR {status}")

    def get_bias_data(self):
        """
        Method to get all data for BIAS.
        """
        return self.manipulate(f"BIAS:{self.bias_dev}:DATA?")

    def get_ctrl_data(self):
        """
        Method to get all data for CTRL.
        """
        return self.manipulate(f"CTRL:{self.ctrl_dev}:DATA?")

    def test_bias(self):
        """
        Method to get status bias dev.
        """
        return self.manipulate(f"GEN:{self.bias_dev}:STAT?")

    def test_ctrl(self):
        """
        Method to get status ctrl dev.
        """
        return self.manipulate(f"GEN:{self.ctrl_dev}:STAT?")

    def test(self) -> bool:
        """
        Method to test full block.
        """
        bias = self.test_bias()
        logger.info(f"[Block.test] Bias test `{bias}`")
        ctrl = self.test_ctrl()
        logger.info(f"[Block.test] CTRL test `{ctrl}`")
        return bias == "OK" and ctrl == "OK"

    def set_ctrl_current(self, curr: float):
        return self.manipulate(f"CTRL:{self.ctrl_dev}:CURR {curr}")

    def get_ctrl_current(self) -> Union[float, None]:
        for attempt in range(1, 6):
            try:
                return float(self.manipulate(f"CTRL:{self.ctrl_dev}:CURR?"))
            except ValueError as e:
                logger.debug(f"Exception[get_ctrl_current] {e}; attempt {attempt}")
                continue
        return None

    def get_bias_current(self) -> Union[float, None]:
        for attempt in range(1, 6):
            try:
                return float(self.manipulate(f"BIAS:{self.bias_dev}:CURR?"))
            except ValueError as e:
                logger.debug(
                    f"[Block.get_bias_current][Exception] {e}, attempt {attempt}"
                )
                continue
        return None

    def get_bias_voltage(self) -> Union[float, None]:
        for attempt in range(1, 6):
            try:
                return float(self.manipulate(f"BIAS:{self.bias_dev}:VOLT?"))
            except ValueError as e:
                logger.debug(
                    f"[Block.get_bias_voltage] Exception {e}; attempt {attempt}"
                )
                continue
        return None

    def set_bias_voltage(self, volt: float) -> None:
        for attempt in range(1, 6):
            status = self.manipulate(f"BIAS:{self.bias_dev}:VOLT {volt}")
            if status == "OK":
                logger.debug(
                    f"[Block.set_bias_voltage] Success set volt {volt}; status {status}; attempt {attempt}"
                )
                return
            logger.warning(
                f"[Block.set_bias_voltage] unable to set volt {volt}; received {status}; attempt {attempt}"
            )
            continue
        return

    def get_resistance(self) -> float:
        """
        Getting the equivalent resistance used for current measurement in a 5-point bias circuit [Ohm]
        :return:
        """
        return float(self.manipulate(f"BIAS:{self.bias_dev}:CMRE?"))

    def __del__(self):
        self.disconnect()
        logger.info(f"[Block.__del__] Instance {self} deleted")


if __name__ == "__main__":
    block = SisBlock(state.BLOCK_ADDRESS, state.BLOCK_PORT)
    block.connect()
    print(block.set_bias_short_status(0))
    print(block.get_bias_data())
    print(block.set_bias_short_status(1))

    print(block.set_ctrl_short_status(0))
    print(block.get_ctrl_data())
    print(block.set_ctrl_short_status(1))
    print(block.test_bias())
    block.disconnect()
