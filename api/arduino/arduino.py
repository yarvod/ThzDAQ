import serial


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

    def __del__(self) -> None:
        self.adapter.close()


if __name__ == "__main__":
    angle = float(input("Angle: "))
    ard = StepMotorManager()
    ard.rotate(angle)
