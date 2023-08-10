import socket
import time
from typing import Union

from settings import ADAPTERS, SOCKET
from state import state
from utils.classes import BaseInstrumentInterface
from utils.decorators import exception
from utils.functions import import_class
from utils.logger import logger


class Block(BaseInstrumentInterface):
    """
    Scontel SIS block operation interface.
    """

    def __init__(
        self,
        host: str = state.BLOCK_ADDRESS,
        port: int = state.BLOCK_PORT,
        bias_dev: str = state.BLOCK_BIAS_DEV,
        ctrl_dev: str = state.BLOCK_CTRL_DEV,
        adapter: str = SOCKET,
        *args,
        **kwargs,
    ):
        self.host = host
        self.port = port
        self.bias_dev = bias_dev
        self.ctrl_dev = ctrl_dev

        self.adapter_name = adapter
        self.adapter = None

        if self.adapter is None:
            self._set_adapter(adapter, *args, **kwargs)

    def _set_adapter(self, adapter: str, *args, **kwargs) -> None:
        adapter_path = ADAPTERS.get(adapter)
        try:
            adapter_class = import_class(adapter_path)
            self.adapter = adapter_class(
                host=self.host, port=self.port, *args, **kwargs
            )
        except (ImportError, ImportWarning) as e:
            logger.error(f"[{self.__class__.__name__}._set_adapter] {e}")

    @exception
    def connect(self):
        if self.adapter.is_socket_closed():
            self.adapter.connect()

    @exception
    def disconnect(self):
        logger.info(f"Disconnected from Block {self.host}:{self.port}")

    def get_ctrl_short_status(self, s: socket.socket = None):
        """
        Method to get Short status for CTRL.
        Shorted = 1
        Opened = 0
        """
        return self.adapter.query(f"CTRL:{self.ctrl_dev}:SHOR?")

    def set_ctrl_short_status(self, status: str):
        """
        Method to set Short status for CTRL.
        Shorted = 1
        Opened = 0
        """
        return self.adapter.write(f"CTRL:{self.ctrl_dev}:SHOR {status}")

    def get_bias_short_status(self):
        """
        Method to get Short status for BIAS.
        Shorted = 1
        Opened = 0
        """
        return self.adapter.query(f"BIAS:{self.bias_dev}:SHOR?")

    def set_bias_short_status(self, status: str):
        """
        Method to set Short status for BIAS.
        Shorted = 1
        Opened = 0
        """
        return self.adapter.write(f"BIAS:{self.bias_dev}:SHOR {status}")

    def get_bias_data(self):
        """
        Method to get all data for BIAS.
        """
        return self.adapter.query(f"BIAS:{self.bias_dev}:DATA?")

    def get_ctrl_data(self):
        """
        Method to get all data for CTRL.
        """
        return self.adapter.query(f"CTRL:{self.ctrl_dev}:DATA?")

    def test_bias(self):
        """
        Method to get status bias dev.
        """
        return self.adapter.query(f"GEN:{self.bias_dev}:STAT?")

    def test_ctrl(self):
        """
        Method to get status ctrl dev.
        """
        return self.adapter.query(f"GEN:{self.ctrl_dev}:STAT?")

    def test(self):
        """
        Method to test full block.
        """
        bias = self.test_bias()
        logger.info(f"[Block.test] Bias test `{bias}`")
        ctrl = self.test_ctrl()
        logger.info(f"[Block.test] CTRL test `{ctrl}`")
        if bias == "OK" and ctrl == "OK":
            return "OK"
        return "ERROR"

    def set_ctrl_current(self, curr: float):
        self.adapter.write(f"CTRL:{self.ctrl_dev}:CURR {curr}")

    def get_ctrl_current(self) -> Union[float, None]:
        for attempt in range(5):
            try:
                if attempt > 1:
                    time.sleep(0.1)
                return float(self.adapter.query(f"CTRL:{self.ctrl_dev}:CURR?"))
            except ValueError as e:
                logger.debug(f"Exception[get_ctrl_current] {e}; attempt {attempt}")
                continue
        return None

    def get_bias_current(self) -> Union[float, None]:
        for attempt in range(1, 6):
            try:
                if attempt > 1:
                    time.sleep(0.1)
                result = float(self.adapter.query(f"BIAS:{self.bias_dev}:CURR?"))
                logger.debug(
                    f"Success [Block.get_bias_current] received {result} current; attempt {attempt}"
                )
                return result
            except Exception as e:
                logger.debug(
                    f"[Block.get_bias_current][Exception] {e}, attempt {attempt}"
                )
                continue
        return None

    def get_bias_voltage(self) -> Union[float, None]:
        for attempt in range(1, 6):
            try:
                if attempt > 1:
                    time.sleep(0.1)
                result = float(self.adapter.query(f"BIAS:{self.bias_dev}:VOLT?"))
                logger.debug(
                    f"[Block.get_bias_voltage] Success received {result} voltage; attempt {attempt}"
                )
                return result
            except Exception as e:
                logger.debug(
                    f"[Block.get_bias_voltage] Exception {e}; attempt {attempt}"
                )
                continue
        return None

    def set_bias_voltage(self, volt: float) -> None:
        for attempt in range(1, 6):
            status = self.adapter.write(f"BIAS:{self.bias_dev}:VOLT {volt}")
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

    def __del__(self):
        self.disconnect()
        logger.info(f"[Block.__del__] Instance {self} deleted")


if __name__ == "__main__":
    block = Block(state.BLOCK_ADDRESS, state.BLOCK_PORT)
    block.connect()
    print(block.set_bias_short_status(0))
    print(block.get_bias_data())
    print(block.set_bias_short_status(1))

    print(block.set_ctrl_short_status(0))
    print(block.get_ctrl_data())
    print(block.set_ctrl_short_status(1))
    print(block.test_bias())
    block.disconnect()
