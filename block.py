import socket
from collections import defaultdict

from config import BLOCK_ADDRESS, BLOCK_PORT


class Block:

    def __init__(self, host: str, port: int, bias_dev: str = 'DEV4', ctrl_dev: str = 'DEV3'):
        self.host = host
        self.port = port
        self.bias_dev = bias_dev
        self.ctrl_dev = ctrl_dev
        self.iv = defaultdict(list)

    def manipulate(self, cmd: str):
        if type(cmd) != bytes:
            cmd = bytes(cmd, 'utf-8')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))
            s.sendall(cmd)
            data = s.recv(1024)
        return data.decode().rstrip()

    def set_ctrl_current(self, curr: float):
        return self.manipulate(f'CTRL:{self.ctrl_dev}:CURR {curr}')

    def get_ctrl_current(self):
        return self.manipulate(f'CTRL:{self.ctrl_dev}:CURR?')

    def get_current(self):
        return self.manipulate(f'BIAS:{self.bias_dev}:CURR?')

    def get_voltage(self):
        return self.manipulate(f'BIAS:{self.bias_dev}:VOLT?')

    def set_voltage(self, volt: float):
        return self.manipulate(f'BIAS:{self.bias_dev}:VOLT {volt}')


if __name__ == '__main__':
    block = Block(BLOCK_ADDRESS, BLOCK_PORT)

    # print(block.set_voltage(0.1))
    # print(block.get_current())
    print(block.set_ctrl_current(0.0002))
