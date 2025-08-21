import json
import logging
import re
from typing import Dict, Union, Any

import serial

from api.Pfeiffer.data_types import PFEIFFER_DATA_TYPES
import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class HiCube:
    def __init__(
        self,
        # host: str = "169.254.54.24",
        port: str = "COM20",
        baudrate: int = 9600,
        *args,
        **kwargs,
    ):
        # self.host = host
        self.port = port
        self.baudrate = baudrate
        self.data_types = PFEIFFER_DATA_TYPES
        self.parameters = settings.PFEIFFER_PARAMETERS
        self.client: serial.Serial = None
        self.init_client()

    def init_client(self):
        self.port = str(self.port)
        if self.client is not None:
            if self.client.is_open:
                self.client.close()
        self.client = serial.Serial(
            port=self.port,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            baudrate=self.baudrate,
            timeout=5,
        )

    def connect(self) -> bool:
        if not self.client.is_open:
            self.client.open()
        logger.info(
            f"[{[self.__class__.__name__]}.connect] Connected {self.client.is_open}"
        )
        return self.client.is_open

    def close(self):
        self.client.close()
        logger.info(f"[{[self.__class__.__name__]}.close] Client closed")

    def __del__(self):
        logger.info(f"[{[self.__class__.__name__]}.__del__] Instance deleted")

    def parse_data(self, msg: str) -> Union[None, Dict]:
        slave = msg[:3]
        reg = msg[5:8]
        parameter = next(
            filter(lambda x: x["number"] == reg, self.parameters.values()), None
        )
        if not parameter:
            return
        data_type = self.data_types[parameter["data type"]]
        try:
            end_index = 10 + data_type.length
            typed_value = data_type(msg[10:end_index])
        except ValueError:
            return

        data = {
            "slave": slave,
            "reg": reg,
            "name": parameter["description"],
            "value": typed_value.value,
            "type": typed_value.__str__(),
        }
        return data

    def read_data(self) -> Union[Dict, None]:
        raw_data = self.client.read(int(1.5 * 2048))
        print(f"[{self.__class__.__name__}.read_data] Raw Data {raw_data}")
        raw_data_decoded = raw_data.decode("ascii")
        raw_data_split = raw_data_decoded.split("\r")
        full_data = {
            "001": {},
            "002": {},
        }
        for msg in raw_data_split:
            if "?" in msg:
                continue
            data = self.parse_data(msg)
            if data is None:
                continue
            full_data[data["slave"]][data["reg"]] = data

        return full_data

    def get_query_telegram(self, reg: int, slv: int) -> str:
        act = "00"
        command = f"{slv:03}{act:02}{reg:03}02=?"
        checksum = sum(ord(el) for el in command) % 256
        command += f"{checksum:03}" + "\r"
        telegram = "".join([str(ord(char)) for char in command])
        return telegram

    def get_parameter(self, param: Union[str, int]) -> Dict:
        if type(param) == int:
            param = f"{param:03}"
        return next(
            filter(lambda x: x["number"] == param, self.parameters.values()), None
        )

    def get_control_telegram(self, reg: str, data: Any, slv: str) -> Union[str, None]:
        act = "10"  # write holding register
        parameter = self.get_parameter(reg)
        if not parameter:
            return
        data_type = self.data_types[parameter["data type"]]
        data = data_type(instance=data)
        command = f"{slv:03}{act:02}{reg:03}{data.length:02}{data.value_device}"
        checksum = sum(ord(el) for el in command) % 256
        command += f"{checksum:03}" + "\r"
        telegram = "".join([str(ord(char)) for char in command])
        return telegram

    def get_data(self, reg: int, slv: int):
        telegram = self.get_query_telegram(reg=reg, slv=slv)
        self.client.write(telegram.encode("ascii"))
        raw_data = self.client.read(2 * 1024)
        # raw_data = self.client.readline()
        print(raw_data)
        raw_data_decoded = re.sub(r"\\[xX][a-z0-9a-z]+", "", f"{raw_data}")[2:-1].split(
            "\\r"
        )
        full_data = {
            "001": {},
            "002": {},
        }
        for msg in raw_data_decoded:
            if "?" in msg or "x" in msg or not msg:
                continue
            data = self.parse_data(msg)
            if data is None:
                continue
            full_data[data["slave"]][data["reg"]] = data

        return full_data


if __name__ == "__main__":
    pump = HiCube(port="COM14")
    # print(pump.read_data())
    # pump.write_register("010", True, "042")
    # dd = pump.get_data(340, 1)
    dd = pump.read_data()
    print(dd)
    with open("dd.json", "w") as f:
        json.dump(dd, f, indent=4)
