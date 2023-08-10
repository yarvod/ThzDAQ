import logging
import sys
from typing import Tuple

import serial
from serial.tools.list_ports import main as list_ports


logger = logging.getLogger(__name__)


class StepMotorManager:
    MAX_STEPS = 1000

    def __init__(
        self,
        address: str = "COM5",
        timeout: float = 5,
    ):
        self.address = address
        self.adapter = serial.Serial(address, 9600, timeout=timeout)

    def rotate(self, angle: float = 90) -> None:
        """Rotate method
        Params:
            angle: float - Angle in degrees
        """
        self.adapter.write(f"{angle}\n".encode())

    @classmethod
    def test(cls, address, timeout=5) -> Tuple[bool, str]:
        """Simple test func"""
        try:
            adapter = serial.Serial(address, 9600, timeout=timeout)
            adapter.write(f"test\n".encode())
            response = adapter.readline().decode(encoding="utf-8").rstrip()
            return response == "OK", response
        except Exception as e:
            logger.error(f"[{cls.__name__}.test] {e}")
            return False, f"{e}"

    @staticmethod
    def scan_ports():
        list_ports()

    def __del__(self) -> None:
        self.adapter.close()


if __name__ == "__main__":
    dev = sys.argv[1]
    angle = float(sys.argv[2])
    ard = StepMotorManager(address=dev)
    ard.rotate(angle)
