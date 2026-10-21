import json
from typing import Any, Dict, Optional, Protocol

from thzdaq_instruments.errors import (
    InstrumentConnectionError,
    InstrumentResponseError,
    InstrumentTimeoutError,
)
from thzdaq_instruments.transport.base import ConnectionSpec


class JsonClient(Protocol):
    def get(self, path: str) -> Dict[str, Any]:
        ...

    def post(self, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ...

    def close(self) -> None:
        ...


class JsonHttpClient:
    """JSON over HTTP for REST instruments; errors become InstrumentError."""

    def __init__(self, spec: ConnectionSpec, scheme: str = "http"):
        import requests

        self._requests = requests
        self.base_url = f"{scheme}://{spec.host}" + (
            f":{spec.port}" if spec.port else ""
        )
        self.timeout = spec.timeout
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

    def _request(self, method: str, path: str, data=None) -> Dict[str, Any]:
        url = self.base_url + path
        try:
            response = self._session.request(
                method,
                url,
                data=None if data is None else json.dumps(data),
                timeout=self.timeout,
            )
        except self._requests.Timeout as e:
            raise InstrumentTimeoutError(f"{method} {url}: timeout") from e
        except self._requests.RequestException as e:
            raise InstrumentConnectionError(f"{method} {url}: {e}") from e
        if response.status_code >= 400:
            raise InstrumentResponseError(
                f"{method} {url}: HTTP {response.status_code} {response.text[:200]!r}"
            )
        if not response.content:
            return {}
        try:
            data = response.json()
        except ValueError:
            # Simple firmwares (e.g. the Arduino grid) answer plain text
            return {"text": response.text}
        return data if isinstance(data, dict) else {"data": data}

    def get(self, path: str) -> Dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("POST", path, data)

    def close(self) -> None:
        self._session.close()
