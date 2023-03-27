import socket
from collections import defaultdict

from config import BLOCK_ADDRESS, BLOCK_PORT, BLOCK_BIAS_DEV, BLOCK_CTRL_DEV


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


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
        try:
            s.connect((self.host, self.port))
            s.sendall(cmd)
            data = s.recv(1024)
            result = data.decode().rstrip()
        except OSError as e:
            result = f"ERROR: {e}"
        return result

    def get_ctrl_short_status(self, s: socket.socket = None):
        """
        Method to get Short status for CTRL.
        Shorted = 1
        Opened = 0
        """
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
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
                return self.manipulate(f"BIAS:{self.bias_dev}:SHOR {status}", s)
        return self.manipulate(f"BIAS:{self.bias_dev}:SHOR {status}", s)

    def get_bias_data(self, s: socket.socket = None):
        """
        Method to get all data for BIAS.
        """
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return self.manipulate(f"BIAS:{self.bias_dev}:DATA?", s)
        return self.manipulate(f"BIAS:{self.bias_dev}:DATA?", s)

    def get_ctrl_data(self, s: socket.socket = None):
        """
        Method to get all data for CTRL.
        """
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return self.manipulate(f"CTRL:{self.ctrl_dev}:DATA?", s)
        return self.manipulate(f"CTRL:{self.ctrl_dev}:DATA?", s)

    def set_ctrl_current(self, curr: float, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return self.manipulate(f"CTRL:{self.ctrl_dev}:CURR {curr}", s)
        return self.manipulate(f"CTRL:{self.ctrl_dev}:CURR {curr}", s)

    def get_ctrl_current(self, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return self.manipulate(f"CTRL:{self.ctrl_dev}:CURR?", s)
        return self.manipulate(f"CTRL:{self.ctrl_dev}:CURR?", s)

    def get_bias_current(self, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return self.manipulate(f"BIAS:{self.bias_dev}:CURR?", s)
        return self.manipulate(f"BIAS:{self.bias_dev}:CURR?", s)

    def get_bias_voltage(self, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return self.manipulate(f"BIAS:{self.bias_dev}:VOLT?", s)
        return self.manipulate(f"BIAS:{self.bias_dev}:VOLT?", s)

    def set_bias_voltage(self, volt: float, s: socket.socket = None):
        if s is None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return self.manipulate(f"BIAS:{self.bias_dev}:VOLT {volt}", s)
        return self.manipulate(f"BIAS:{self.bias_dev}:VOLT {volt}", s)

    # def scan_cl_current(self, volt, cl_i_from, sis_i_from):
    #     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    #


if __name__ == "__main__":
    block = Block(BLOCK_ADDRESS, BLOCK_PORT)
    print(block.set_bias_short_status(0))
    print(block.get_bias_data())
    print(block.set_bias_short_status(1))

    print(block.set_ctrl_short_status(0))
    print(block.get_ctrl_data())
    print(block.set_ctrl_short_status(1))
