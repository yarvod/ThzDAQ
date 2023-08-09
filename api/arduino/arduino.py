import sys

import serial
from serial.tools.list_ports import main as list_ports


class StepMotorManager:
    MAX_STEPS = 1000

    def __init__(
        self,
        address: str = "COM5",
    ):
        self.address = address
        self.adapter = serial.Serial(address, 9600, timeout=5)

    def rotate(self, angle: float = 90) -> None:
        """Rotate method
        Params:
            angle: float - Angle in degrees
        """
        self.adapter.write(f"{angle}\n".encode())

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
