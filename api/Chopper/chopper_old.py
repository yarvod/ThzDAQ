import asyncio
import time
from pymodbus.client import AsyncModbusTcpClient as ModbusClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.payload import BinaryPayloadDecoder

# Configuration
slave_address = 1  # Modbus slave address
host: str = "169.254.54.24"
port: int = 1111
baudrate = 9600  # Baudrate (match with the device)


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class Chopper:
    def __init__(self):
        """Initialize."""
        self.client = ModbusClient(
            method="rtu",
            host=host,
            port=port,
            baudrate=baudrate,
            stopbits=1,
            bytesize=8,
            parity="N",
        )

    async def save_parameters_to_eeprom(self):
        self.client.write_register(int(0x1801), int(0x2211), slave_address)

    async def motor_direction(self, param):
        # 0:CW; 1:CCW
        await self.client.write_register(int(0x007), int(param), slave_address)

    async def jog_speed(self, param):
        # 0--5000 rpm
        await self.client.write_register(int(0x01E1), int(param), slave_address)

    async def jog_acc_dec_time(self, param):
        # in ms/1000rpm
        await self.client.write_register(int(0x01E7), int(param), slave_address)

    async def jogCW(self):
        await self.client.write_register(int(0x1801), int(0x4001), slave_address)
        print("jogCW")

    async def jogCCW(self):
        await self.client.write_register(int(0x1801), int(0x4002), slave_address)
        print("jogCCW")

    async def emergency_stop(self):
        await self.client.write_register(int(0x6002), int(0x040), slave_address)
        print("Emergency stop")

    async def set_origin(self):
        await self.client.write_register(int(0x6002), int(0x021), slave_address)
        pos = await self.get_actual_pos()
        print("Origin set, actual position (in pulses): ", pos)

    async def get_actual_pos(self):
        start_address = int(0x602C)
        count = 2
        result = await self.client.read_holding_registers(start_address, count, 1)
        decoder = BinaryPayloadDecoder.fromRegisters(
            result.registers, byteorder=Endian.BIG, wordorder=Endian.BIG
        )
        actual_pos = decoder.decode_32bit_int()
        return actual_pos

    async def get_actual_speed(self):
        t1 = time.time()
        x1 = await self.get_actual_pos()
        time.sleep(0.1)
        t2 = time.time()
        x2 = await self.get_actual_pos()
        speed = (x2 - x1) / (10000 * (t2 - t1))
        return speed

    # CW by 90 deg
    async def path0(self):
        await self.client.write_register(
            int(0x6200), int(0b01000001), slave_address
        )  # relative position mode
        # position high bits
        await self.client.write_register(int(0x6201), int(0), slave_address)
        # position low bits
        await self.client.write_register(
            int(0x6202), int(2500), slave_address
        )  # 10000 ppr, equals to 90 deg rotation
        # turn speed
        await self.client.write_register(int(0x6203), int(25), slave_address)
        # acc/decc time
        await self.client.write_register(int(0x6204), int(5000), slave_address)
        await self.client.write_register(int(0x6205), int(10000), slave_address)
        # trigger PR0 motion
        if (
            abs(
                await self.get_actual_pos()
                - (int(await self.get_actual_pos() / 2500) * 2500)
            )
            > 50
        ):
            await self.align()
            time.sleep(0.3)
            await self.client.write_register(int(0x6002), int(0x010), slave_address)
            print("open/close")
        else:
            await self.client.write_register(int(0x6002), int(0x010), slave_address)
            print("open/close")

    # Constant speed
    async def set_frequency(self, frequency):
        self.frequency = frequency  # Hz
        omega = frequency * 60
        await self.client.write_register(int(0x620B), int(omega), slave_address)

    async def path1(self):
        await self.client.write_register(
            int(0x6208), int(0b0010), slave_address
        )  # velocity mode
        # Angular speed (rpm)
        # freq = 12  # Hz
        # omega = freq * 60
        # await self.client.write_register(int(0x620B), int(omega), slave_address)

        # acc/dec (ms/1000 rpm)
        await self.client.write_register(int(0x620C), int(10000), slave_address)
        await self.client.write_register(int(0x620D), int(5000), slave_address)
        # trigger PR1 motion
        await self.client.write_register(int(0x6002), int(0x011), slave_address)
        # print("Constant speed:", freq, "Hz")

    # slow down
    async def path2(self):
        print("!Axis in rotation!")
        print("Slowing down, wait for complete stop ...")
        while True:
            await self.client.write_register(
                int(0x6210), int(0b01000001), slave_address
            )  # relative position mode
            # position high bits
            await self.client.write_register(int(0x6211), int(0), slave_address)
            # position low bits
            await self.client.write_register(int(0x6212), int(0), slave_address)
            # turn speed
            await self.client.write_register(int(0x6213), int(4), slave_address)
            # acc/decc time
            await self.client.write_register(int(0x6214), int(12000), slave_address)
            await self.client.write_register(int(0x6215), int(12000), slave_address)
            # trigger PR0 motion
            await self.client.write_register(int(0x6002), int(0x012), slave_address)
            if await self.get_actual_speed() < 0.1:
                await self.emergency_stop()
                break

    async def go_to_pos(self, pulse):
        starting_address = int(0x6219)
        builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
        builder.add_32bit_int(pulse)
        registers = builder.to_registers()
        await self.client.write_registers(starting_address, registers, slave_address)
        # print("Moving to position: p = ", pulse, "...")

        await self.client.write_register(
            int(0x6218), int(0b00000001), slave_address
        )  # absolute position mode
        # Angular speed (rpm)
        await self.client.write_register(int(0x621B), int(25), slave_address)
        # acc/dec (ms/100 rpm)
        await self.client.write_register(int(0x621C), int(3000), slave_address)
        await self.client.write_register(int(0x621D), int(3000), slave_address)
        # trigger PR2 motion
        await self.client.write_register(int(0x6002), int(0x013), slave_address)

    async def align(self):
        actual_pos = await self.get_actual_pos()
        # print("Actual position: ", actual_pos)
        target = round(actual_pos / 2500) * 2500
        await self.go_to_pos(target)


if __name__ == "__main__":

    async def main():
        chopper = Chopper()
        await chopper.client.connect()
        await chopper.path2()

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
