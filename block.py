import socket
from collections import defaultdict

from config import BLOCK_ADDRESS, BLOCK_PORT


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class Block(metaclass=Singleton):

    def __init__(self, host: str, port: int, bias_dev: str = 'DEV4', ctrl_dev: str = 'DEV3'):
        self.host = host
        self.port = port
        self.bias_dev = bias_dev
        self.ctrl_dev = ctrl_dev
        self.iv = defaultdict(list)

    def manipulate(self, cmd: str, s: socket.socket):
        if type(cmd) != bytes:
            cmd = bytes(cmd, 'utf-8')
        s.connect((self.host, self.port))
        s.sendall(cmd)
        data = s.recv(1024)
        return data.decode().rstrip()

    def set_ctrl_current(self, curr: float):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return self.manipulate(f'CTRL:{self.ctrl_dev}:CURR {curr}', s)

    def get_ctrl_current(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return self.manipulate(f'CTRL:{self.ctrl_dev}:CURR?', s)

    def get_current(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return self.manipulate(f'BIAS:{self.bias_dev}:CURR?', s)

    def get_voltage(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return self.manipulate(f'BIAS:{self.bias_dev}:VOLT?', s)

    def set_voltage(self, volt: float):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return self.manipulate(f'BIAS:{self.bias_dev}:VOLT {volt}', s)

    # def scan_cl_current(self, volt, cl_i_from, sis_i_from):
    #     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    #


if __name__ == '__main__':
    block = Block(BLOCK_ADDRESS, BLOCK_PORT)

    # print(block.set_voltage(0.1))
    # print(block.get_current())
    print(block.set_ctrl_current(0.0002))
