import socket
import time
import logging
from typing import Union, Optional

from store.state import state
from utils.classes import BaseInstrumentInterface
from utils.decorators import exception


logger = logging.getLogger(__name__)


class SisBlock(BaseInstrumentInterface):
    """
    Scontel SIS block operation interface.
    """

    def __init__(
        self,
        host: str = state.BLOCK_ADDRESS,
        port: int = state.BLOCK_PORT,
        bias_dev: str = state.BLOCK_BIAS_DEV,
        ctrl_dev: str = state.BLOCK_CTRL_DEV,
    ):
        self.host = host
        self.port = port
        self.bias_dev = bias_dev
        self.ctrl_dev = ctrl_dev
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    @exception
    def connect(self):
        self.s.settimeout(10)
        try:
            self.s.connect((self.host, self.port))
            logger.info(f"Connected to Block {self.host}:{self.port}")
        except Exception as e:
            logger.warning(f"Warning[Block.connect] {e}")
        self.s.settimeout(2)

    @exception
    def disconnect(self):
        self.s.close()
        logger.info(f"Disconnected from Block {self.host}:{self.port}")

    def manipulate(self, cmd: str) -> str:
        """
        Base method to send command to block.
        Parameters:
            cmd (str): SCPI string command
        Returns:
            result (str): Block answer
        """
        cmd = bytes(cmd, "utf-8")
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                self.s.send(cmd)
                time.sleep(0.05)
                data = self.s.recv(1024 * 1024)
                result = data.decode("ISO-8859-1").rstrip()
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

    def set_bias_voltage_iterative(
        self, desired_voltage, tolerance=0.001, max_iterations=500
    ) -> Optional[float]:
        voltage_to_set = desired_voltage
        iteration = 0

        while iteration < max_iterations:
            self.set_bias_voltage(voltage_to_set)
            time.sleep(1)
            real_voltage = self.get_bias_voltage()
            logger.info(f"Real voltage {real_voltage*1e3:.3f}")

            if abs(real_voltage - desired_voltage) <= tolerance * abs(desired_voltage):
                logger.info(
                    f"Желаемое напряжение {desired_voltage*1e3:.3f} достигнуто с точностью {tolerance * 100:.2f}%. за {iteration} итераций"
                )
                return real_voltage

            voltage_to_set += desired_voltage - real_voltage
            logger.info(f"Voltage to set {voltage_to_set*1e3:.3f}")
            iteration += 1

        logger.error(
            f"Не удалось достичь желаемого напряжения {desired_voltage*1e3:.3f} за {max_iterations} итераций."
        )
        return None

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
