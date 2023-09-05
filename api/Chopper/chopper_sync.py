import logging
import time
from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder

from store.state import state

logger = logging.getLogger(__name__)


class Chopper:
    def __init__(
        self,
        host: str = state.CHOPPER_HOST,
        baudrate: int = 9600,
        slave_address: int = 1,
    ):
        self.host = host
        self.baudrate = baudrate
        self.slave_address = slave_address
        self.client = None
        self.init_client()

    def init_client(self, host: str = state.CHOPPER_HOST):
        self.host = host
        if self.client is not None:
            if self.client.connected:
                self.client.close()
            del self.client
        self.client = ModbusClient(
            method="rtu",
            port=self.host,
            baudrate=self.baudrate,
            stopbits=1,
            bytesize=8,
            parity="N",
        )

    def connect(self) -> bool:
        if not self.client.connected:
            self.client.connect()
        logger.info(
            f"[{[self.__class__.__name__]}.connect] Connected {self.client.connected}"
        )
        return self.client.connected

    def close(self):
        self.client.close()
        logger.info(f"[{[self.__class__.__name__]}.close] Client closed")

    def __del__(self):
        logger.info(f"[{[self.__class__.__name__]}.__del__] Instance deleted")

    def save_parameters_to_eeprom(self):
        self.client.write_register(int(0x1801), int(0x2211), self.slave_address)

    def motor_direction(self, param):
        # 0:CW; 1:CCW
        self.client.write_register(int(0x007), int(param), self.slave_address)

    def jog_speed(self, param):
        # 0--5000 rpm
        self.client.write_register(int(0x01E1), int(param), self.slave_address)

    def jog_acc_dec_time(self, param):
        # in ms/1000rpm
        self.client.write_register(int(0x01E7), int(param), self.slave_address)

    def jogCW(self):
        self.client.write_register(int(0x1801), int(0x4001), self.slave_address)
        print("jogCW")

    def jogCCW(self):
        self.client.write_register(int(0x1801), int(0x4002), self.slave_address)
        print("jogCCW")

    def emergency_stop(self):
        self.client.write_register(int(0x6002), int(0x040), self.slave_address)
        print("Emergency stop")

    def set_origin(self):
        """Set current position as 'Zero'"""
        self.client.write_register(int(0x6002), int(0x021), self.slave_address)
        pos = self.get_actual_pos()
        print("Origin set, actual position (in pulses): ", pos)

    def get_actual_pos(self):
        start_address = int(0x602C)
        count = 2
        result = self.client.read_holding_registers(start_address, count, 1)
        decoder = BinaryPayloadDecoder.fromRegisters(
            result.registers, byteorder=Endian.BIG, wordorder=Endian.BIG
        )
        actual_pos = decoder.decode_32bit_int()
        return actual_pos

    def get_actual_speed(self):
        t1 = time.time()
        x1 = self.get_actual_pos()
        time.sleep(0.1)
        t2 = time.time()
        x2 = self.get_actual_pos()
        speed = (x2 - x1) / (10000 * (t2 - t1))
        return speed

    # CW by 90 deg
    def path0(self):
        self.client.write_register(
            int(0x6200), int(0b01000001), self.slave_address
        )  # relative position mode
        # position high bits
        self.client.write_register(int(0x6201), int(0), self.slave_address)
        # position low bits
        self.client.write_register(
            int(0x6202), int(2500), self.slave_address
        )  # 10000 ppr, equals to 90 deg rotation
        # turn speed
        self.client.write_register(int(0x6203), int(25), self.slave_address)
        # acc/decc time
        self.client.write_register(int(0x6204), int(5000), self.slave_address)
        self.client.write_register(int(0x6205), int(10000), self.slave_address)
        # trigger PR0 motion
        if abs(self.get_actual_pos() - (int(self.get_actual_pos() / 2500) * 2500)) > 50:
            self.align()
            time.sleep(0.3)
            self.client.write_register(int(0x6002), int(0x010), self.slave_address)
            print("open/close")
        else:
            self.client.write_register(int(0x6002), int(0x010), self.slave_address)
            print("open/close")

    # Constant speed
    def freq(self, frequency):
        self.frequency = frequency  # Hz
        omega = frequency * 60
        self.client.write_register(int(0x620B), int(omega), self.slave_address)

    def path1(self):
        self.client.write_register(
            int(0x6208), int(0b0010), self.slave_address
        )  # velocity mode
        # Angular speed (rpm)
        # freq = 12  # Hz
        # omega = freq * 60
        # self.client.write_register(int(0x620B), int(omega), self.slave_address)

        # acc/dec (ms/1000 rpm)
        self.client.write_register(int(0x620C), int(10000), self.slave_address)
        self.client.write_register(int(0x620D), int(5000), self.slave_address)
        # trigger PR1 motion
        self.client.write_register(int(0x6002), int(0x011), self.slave_address)
        # print("Constant speed:", freq, "Hz")

    # slow down
    def path2(self):
        print("!Axis in rotation!")
        print("Slowing down, wait for complete stop ...")
        while True:
            self.client.write_register(
                int(0x6210), int(0b01000001), self.slave_address
            )  # relative position mode
            # position high bits
            self.client.write_register(int(0x6211), int(0), self.slave_address)
            # position low bits
            self.client.write_register(int(0x6212), int(0), self.slave_address)
            # turn speed
            self.client.write_register(int(0x6213), int(4), self.slave_address)
            # acc/decc time
            self.client.write_register(int(0x6214), int(12000), self.slave_address)
            self.client.write_register(int(0x6215), int(12000), self.slave_address)
            # trigger PR0 motion
            self.client.write_register(int(0x6002), int(0x012), self.slave_address)
            if self.get_actual_speed() < 0.1:
                self.emergency_stop()
                break

    def go_to_pos(self, pulse):
        starting_address = int(0x6219)
        builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
        builder.add_32bit_int(pulse)
        registers = builder.to_registers()
        self.client.write_registers(starting_address, registers, self.slave_address)
        # print("Moving to position: p = ", pulse, "...")

        self.client.write_register(
            int(0x6218), int(0b00000001), self.slave_address
        )  # absolute position mode
        # Angular speed (rpm)
        self.client.write_register(int(0x621B), int(25), self.slave_address)
        # acc/dec (ms/100 rpm)
        self.client.write_register(int(0x621C), int(3000), self.slave_address)
        self.client.write_register(int(0x621D), int(3000), self.slave_address)
        # trigger PR2 motion
        self.client.write_register(int(0x6002), int(0x013), self.slave_address)

    def align(self):
        actual_pos = self.get_actual_pos()
        # print("Actual position: ", actual_pos)
        target = round(actual_pos / 2500) * 2500
        self.go_to_pos(target)


chopper = Chopper()


if __name__ == "__main__":

    def main():
        chopper = Chopper()
        chopper.connect()
        chopper.path0()

    main()
