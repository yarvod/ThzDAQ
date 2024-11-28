import json
from typing import Optional, Literal

import requests

from store.state import state
from utils.functions import linear


YigType = Literal["yig_1", "yig_2"]


class NiYIGManager:
    def __init__(
        self,
        host: str = state.NI_IP,
    ):
        self.url = f"{state.NI_PREFIX}{host}"
        self.headers = {"Content-Type": "application/json"}

    def test(self) -> bool:
        response = requests.get(self.url, headers=self.headers)
        return response.status_code == 200

    def get_devices(self):
        url = f"{self.url}/devices/"
        response = requests.get(url, headers=self.headers)
        return response.json()

    def start_task(self, device: str = "Dev1"):
        url = f"{self.url}/devices/{device}/start"
        response = requests.post(url, headers=self.headers)
        return response.json()

    def stop_task(self, device: str = "Dev1"):
        url = f"{self.url}/devices/{device}/stop"
        response = requests.post(url, headers=self.headers)
        return response.json()

    def close_task(self, device: str = "Dev1"):
        url = f"{self.url}/devices/{device}/close"
        response = requests.post(url, headers=self.headers)
        return response.json()

    def write_task(self, value: int, yig: YigType = "yig_1", device: str = "Dev1"):
        value = int(value)
        url = f"{self.url}/devices/{device}/write/{yig}/"
        response = requests.post(
            url, data=json.dumps({"value": value}), headers=self.headers
        )
        return response.json()

    def device_reset(self, device: str = "Dev1"):
        url = f"{self.url}/devices/{device}/reset"
        response = requests.post(url, headers=self.headers)
        return response.json()

    def set_frequency(
        self, frequency: float, yig: YigType = "yig_1"
    ) -> Optional[float]:
        """Set frequency Hz directly"""
        value = int(
            linear(
                frequency,
                *state.CALIBRATION_DIGITAL_FREQ_2_POINT,
            )
        )
        resp = self.write_task(value=value, yig=yig)
        resp_int = resp.get("result", None)
        if resp_int is None:
            return None
        else:
            return round(
                linear(resp_int, *state.CALIBRATION_DIGITAL_POINT_2_FREQ) * 1e-9,
                2,
            )


if __name__ == "__main__":
    ...
