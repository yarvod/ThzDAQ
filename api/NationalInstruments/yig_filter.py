import json

import requests

from store.state import state


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

    def write_task(self, value: int, device: str = "Dev1"):
        value = int(value)
        url = f"{self.url}/devices/{device}/write"
        response = requests.post(
            url, data=json.dumps({"value": value}), headers=self.headers
        )
        return response.json()

    def device_reset(self, device: str = "Dev1"):
        url = f"{self.url}/devices/{device}/reset"
        response = requests.post(url, headers=self.headers)
        return response.json()


if __name__ == "__main__":
    ...
