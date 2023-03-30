import logging
import socket
from collections import defaultdict

import numpy as np

from config import BLOCK_ADDRESS, BLOCK_PORT, BLOCK_BIAS_DEV, BLOCK_CTRL_DEV
from utils import Singleton
from vna import VNABlock

logger = logging.getLogger(__name__)


class Block(metaclass=Singleton):
    """
    Scontel SIS block operation interface.
    """

    def __init__(
        self,
        host: str = BLOCK_ADDRESS,
        port: int = BLOCK_PORT,
        bias_dev: str = BLOCK_BIAS_DEV,
        ctrl_dev: str = BLOCK_CTRL_DEV,
    ):
        self.host = host
        self.port = port
        self.bias_dev = bias_dev
        self.ctrl_dev = ctrl_dev
        self.iv = defaultdict(list)

    def manipulate(self, cmd: str, s: socket.socket) -> str:
        """
        Base method to send command to block.
        Parameters:
            cmd (str): SCPI string command
            s (socket.socket): Socket instance Required!
        Returns:
            result (str): Block answer
        """
        if type(cmd) != bytes:
            cmd = bytes(cmd, "utf-8")
        attempt = 0
        max_attempts = 5
        while attempt < max_attempts:
            attempt += 1
            try:
                s.sendall(cmd)
                data = s.recv(1024)
                result = data.decode().rstrip()
                logger.info(f"Received result: {result}; attempt {attempt}")
                return result
            except Exception as e:
                logger.error(f"Exception: {e}; attempt {attempt}")
                continue
        return "0"

    def get_ctrl_short_status(self, s: socket.socket = None):
        """
        Method to get Short status for CTRL.
        Shorted = 1
        Opened = 0
        """
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                return self.manipulate(f"CTRL:{self.ctrl_dev}:SHOR?", s)
        return self.manipulate(f"CTRL:{self.ctrl_dev}:SHOR?", s)

    def set_ctrl_short_status(self, status: int, s: socket.socket = None):
        """
        Method to set Short status for CTRL.
        Shorted = 1
        Opened = 0
        """
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                return self.manipulate(f"CTRL:{self.ctrl_dev}:SHOR {status}", s)
        return self.manipulate(f"CTRL:{self.ctrl_dev}:SHOR {status}", s)

    def get_bias_short_status(self, s: socket.socket = None):
        """
        Method to get Short status for BIAS.
        Shorted = 1
        Opened = 0
        """
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                return self.manipulate(f"BIAS:{self.bias_dev}:SHOR?", s)
        return self.manipulate(f"BIAS:{self.bias_dev}:SHOR?", s)

    def set_bias_short_status(self, status: int, s: socket.socket = None):
        """
        Method to set Short status for BIAS.
        Shorted = 1
        Opened = 0
        """
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                return self.manipulate(f"BIAS:{self.bias_dev}:SHOR {status}", s)
        return self.manipulate(f"BIAS:{self.bias_dev}:SHOR {status}", s)

    def get_bias_data(self, s: socket.socket = None):
        """
        Method to get all data for BIAS.
        """
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                return self.manipulate(f"BIAS:{self.bias_dev}:DATA?", s)
        return self.manipulate(f"BIAS:{self.bias_dev}:DATA?", s)

    def get_ctrl_data(self, s: socket.socket = None):
        """
        Method to get all data for CTRL.
        """
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                return self.manipulate(f"CTRL:{self.ctrl_dev}:DATA?", s)
        return self.manipulate(f"CTRL:{self.ctrl_dev}:DATA?", s)

    def set_ctrl_current(self, curr: float, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                return self.manipulate(f"CTRL:{self.ctrl_dev}:CURR {curr}", s)
        return self.manipulate(f"CTRL:{self.ctrl_dev}:CURR {curr}", s)

    def get_ctrl_current(self, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                result = self.manipulate(f"CTRL:{self.ctrl_dev}:CURR?", s)
                try:
                    return float(result)
                except ValueError:
                    return 0
        result = self.manipulate(f"CTRL:{self.ctrl_dev}:CURR?", s)
        try:
            return float(result)
        except ValueError:
            return 0

    def get_bias_current(self, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                result = self.manipulate(f"BIAS:{self.bias_dev}:CURR?", s)
                try:
                    return float(result)
                except ValueError:
                    return 0
        result = self.manipulate(f"BIAS:{self.bias_dev}:CURR?", s)
        try:
            return float(result)
        except ValueError:
            return 0

    def get_bias_voltage(self, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                results = self.manipulate(f"BIAS:{self.bias_dev}:VOLT?", s)
                try:
                    return float(results)
                except ValueError:
                    return 0
        results = self.manipulate(f"BIAS:{self.bias_dev}:VOLT?", s)
        try:
            return float(results)
        except ValueError:
            return 0

    def set_bias_voltage(self, volt: float, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
                return self.manipulate(f"BIAS:{self.bias_dev}:VOLT {volt}", s)
        return self.manipulate(f"BIAS:{self.bias_dev}:VOLT {volt}", s)

    def scan_ctrl_current(
        self, ctrl_i_from: float, ctrl_i_to: float, points_num: int = 50
    ):
        results = {
            "ctrl_i_set": [],
            "ctrl_i_get": [],
            "bias_i": [],
        }
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))
            ctrl_i_range = np.linspace(ctrl_i_from, ctrl_i_to, points_num)
            initial_ctrl_i = self.get_ctrl_current(s)
            for ctrl_i in ctrl_i_range:
                results["ctrl_i_set"].append(ctrl_i * 1e3)
                self.set_ctrl_current(ctrl_i, s)
                results["ctrl_i_get"].append(self.get_ctrl_current(s) * 1e3)
                results["bias_i"].append(self.get_bias_current(s) * 1e6)
            self.set_ctrl_current(initial_ctrl_i, s)
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
        }
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))
            initial_v = self.get_bias_voltage(s)
            v_range = np.linspace(v_from, v_to, points_num)
            for v_set in v_range:
                self.set_bias_voltage(v_set, s)
                v_get = self.get_bias_voltage(s)
                i_get = self.get_bias_current(s)
                results["v_get"].append(v_get)
                results["v_set"].append(v_set)
                results["i_get"].append(i_get)
            self.set_bias_voltage(initial_v, s)

        return results

    def scan_reflection(
        self,
        v_from: float,
        v_to: float,
        points_num: int = 300,
    ) -> dict:
        results = {
            "i_get": [],
            "v_set": [],
            "v_get": [],
            "refl": [],
        }
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))
            initial_v = self.get_bias_voltage(s)
            v_range = np.linspace(v_from, v_to, points_num)
            vna = VNABlock()
            for v_set in v_range:
                self.set_bias_voltage(v_set, s)
                v_get = self.get_bias_voltage(s)
                i_get = self.get_bias_current(s)
                refl = vna.get_data()
                results["v_get"].append(v_get)
                results["v_set"].append(v_set)
                results["i_get"].append(i_get)
                results["refl"].append(refl)
            self.set_bias_voltage(initial_v, s)

        return results


if __name__ == "__main__":
    block = Block(BLOCK_ADDRESS, BLOCK_PORT)
    print(block.set_bias_short_status(0))
    print(block.get_bias_data())
    print(block.set_bias_short_status(1))

    print(block.set_ctrl_short_status(0))
    print(block.get_ctrl_data())
    print(block.set_ctrl_short_status(1))
