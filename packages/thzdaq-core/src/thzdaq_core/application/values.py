"""The last value known of every device quantity, from reads, sets and polls:
what a snapshot shows and what a set changes from."""

import threading
from typing import Any, Dict, Mapping


class KnownValues:
    def __init__(self):
        self._values: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def update(self, ref: str, values: Mapping[str, Any]) -> None:
        with self._lock:
            self._values.setdefault(ref, {}).update(values)

    def get(self, ref: str, key: str) -> Any:
        with self._lock:
            return self._values.get(ref, {}).get(key)

    def all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {ref: dict(values) for ref, values in self._values.items()}
