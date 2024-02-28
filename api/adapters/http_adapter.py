import json
import logging
from typing import Dict, Tuple

import requests


logger = logging.getLogger(__name__)


class HttpAdapter:
    schema = "http://"

    def __init__(
        self,
        host: str,
        port: int = None,
        *args,
        **kwargs,
    ):
        self.host = host
        self.url = self.schema + self.host
        if port:
            self.url += f":{port}"
        self.headers = {"Content-Type": "application/json"}
        self.timeout = kwargs.get("timeout", 10)

    def post(self, url: str, data: Dict = None) -> Tuple[int, Dict]:
        full_url = self.url + url
        response = requests.post(
            full_url, data=json.dumps(data), headers=self.headers, timeout=self.timeout
        )
        try:
            response_dict = response.json()
        except json.JSONDecodeError:
            logger.error(f"[{self.__class__.__name__}.post] Json Decode Error")
            return response.status_code, {"error": "Json Decode error"}
        return response.status_code, response_dict

    def get(self, url: str, params: Dict = None) -> Tuple[int, Dict]:
        full_url = self.url + url
        response = requests.get(
            full_url, params=params, headers=self.headers, timeout=self.timeout
        )
        try:
            response_dict = response.json()
        except json.JSONDecodeError:
            logger.error(f"[{self.__class__.__name__}.post] Json Decode Error")
            return response.status_code, {"error": "Json Decode error"}
        return response.status_code, response_dict

    def close(self):
        ...
