import socket
import time
from collections import defaultdict
from datetime import datetime

import numpy as np
from config import config
from interactors.vna import VNABlock
from utils.decorators import exception
from utils.logger import logger


class Block:
    """
    Scontel SIS block operation interface.
    """

    def __init__(
        self,
        host: str = config.BLOCK_ADDRESS,
        port: int = config.BLOCK_PORT,
        bias_dev: str = config.BLOCK_BIAS_DEV,
        ctrl_dev: str = config.BLOCK_CTRL_DEV,
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
        self.s.settimeout(None)

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
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    time.sleep(0.1)
                self.s.sendall(cmd)
                data = self.s.recv(1024)
                result = data.decode().rstrip()
                logger.debug(
                    f"[Block.manipulate] Received result: {result}; attempt {attempt}"
                )
                if "ERROR" in result:
                    logger.warning(
                        f"Warning[manipulate] Received Error result: {result}; attempt {attempt}"
                    )
                    continue
                return result
            except Exception as e:
                logger.debug(f"[manipulate] Exception: {e}; attempt {attempt}")
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

    def get_ctrl_current(self):
        for attempt in range(5):
            try:
                if attempt > 1:
                    time.sleep(0.1)
                return float(self.manipulate(f"CTRL:{self.ctrl_dev}:CURR?"))
            except ValueError as e:
                logger.debug(f"Exception[get_ctrl_current] {e}; attempt {attempt}")

    def get_bias_current(self):
        for attempt in range(1, 6):
            try:
                if attempt > 1:
                    time.sleep(0.1)
                result = float(self.manipulate(f"BIAS:{self.bias_dev}:CURR?"))
                logger.debug(
                    f"Success [Block.get_bias_current] received {result} current; attempt {attempt}"
                )
                return result
            except Exception as e:
                logger.debug(
                    f"[Block.get_bias_current][Exception] {e}, attempt {attempt}"
                )
        return None

    def get_bias_voltage(self):
        for attempt in range(1, 6):
            try:
                if attempt > 1:
                    time.sleep(0.1)
                result = float(self.manipulate(f"BIAS:{self.bias_dev}:VOLT?"))
                logger.debug(
                    f"[Block.get_bias_voltage] Success received {result} voltage; attempt {attempt}"
                )
                return result
            except Exception as e:
                logger.debug(
                    f"[Block.get_bias_voltage] Exception {e}; attempt {attempt}"
                )
            return None

    def set_bias_voltage(self, volt: float):
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
        return

    def scan_ctrl_current(
        self, ctrl_i_from: float, ctrl_i_to: float, points_num: int = 50
    ):
        results = {
            "ctrl_i_set": [],
            "ctrl_i_get": [],
            "bias_i": [],
        }
        ctrl_i_range = np.linspace(ctrl_i_from, ctrl_i_to, points_num)
        initial_ctrl_i = self.get_ctrl_current()
        start_t = datetime.now()
        for i, ctrl_i in enumerate(ctrl_i_range):
            if i == 0:
                time.sleep(0.1)
            proc = round((i / points_num) * 100, 2)
            results["ctrl_i_set"].append(ctrl_i * 1e3)
            self.set_ctrl_current(ctrl_i)
            results["ctrl_i_get"].append(self.get_ctrl_current() * 1e3)
            results["bias_i"].append(self.get_bias_current() * 1e6)
            delta_t = datetime.now() - start_t
            logger.info(
                f"[scan_ctrl_current] Proc {proc} %; Time {delta_t}; I set {ctrl_i * 1e3}"
            )
        self.set_ctrl_current(initial_ctrl_i)
        return results

    def scan_bias(
        self,
        v_from: float,
        v_to: float,
        points_num: int = 300,
    ) -> dict:
        results = {
            "i_get": [],
            "v_set": [],
            "v_get": [],
            "time": [],
        }
        initial_v = self.get_bias_voltage()
        v_range = np.linspace(v_from, v_to, points_num)
        start_t = datetime.now()
        for i, v_set in enumerate(v_range):
            proc = round((i / points_num) * 100, 2)
            self.set_bias_voltage(v_set)
            if i == 0:
                time.sleep(1)
            v_get = self.get_bias_voltage()
            i_get = self.get_bias_current()
            results["v_get"].append(v_get * 1e3)
            results["v_set"].append(v_set * 1e3)
            results["i_get"].append(i_get * 1e6)
            delta_t = datetime.now() - start_t
            results["time"].append(delta_t)
            logger.info(f"[scan_bias] Proc {proc} %; Time {delta_t}; V_set {v_set}")
        self.set_bias_voltage(initial_v)

        return results

    def scan_reflection(
        self,
        v_from: float,
        v_to: float,
        points_num: int = 300,
        time_per_point: float = 1,
        points_to_average: int = 3,
    ) -> dict:
        results = {
            "i_get": [],
            "v_set": [],
            "v_get": [],
            "refl": defaultdict(np.ndarray),
            "time": [],
        }
        initial_v = self.get_bias_voltage()
        v_range = np.linspace(v_from, v_to, points_num)
        vna = VNABlock()
        start_t = datetime.now()
        for i, v_set in enumerate(v_range):
            proc = round((i / points_num) * 100, 2)
            self.set_bias_voltage(v_set)
            if i == 0:
                time.sleep(1)
            v_get = self.get_bias_voltage()
            i_get = self.get_bias_current()
            time.sleep(0.8)  # waiting for VNA averaging
            refl = vna.get_reflection()
            results["v_get"].append(v_get * 1e3)
            results["v_set"].append(v_set * 1e3)
            results["i_get"].append(i_get * 1e6)
            results["refl"][f"{v_get * 1e3};{i_get * 1e6}"] = refl
            delta_t = datetime.now() - start_t
            results["time"].append(delta_t)
            logger.info(
                f"[scan_reflection] Proc {proc} %; Time {delta_t}; V_set {v_set * 1e3}"
            )
        self.set_bias_voltage(initial_v)

        return results


if __name__ == "__main__":
    block = Block(config.BLOCK_ADDRESS, config.BLOCK_PORT)
    block.connect()
    print(block.set_bias_short_status(0))
    print(block.get_bias_data())
    print(block.set_bias_short_status(1))

    print(block.set_ctrl_short_status(0))
    print(block.get_ctrl_data())
    print(block.set_ctrl_short_status(1))
    print(block.test_bias())
    block.disconnect()
