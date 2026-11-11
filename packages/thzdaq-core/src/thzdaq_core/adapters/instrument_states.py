"""The InstrumentStates port in a JSON file of the daemon (state.json next to
daemon.json; the simulator's state-sim.json): every record by instrument id,
the whole file written again at each change, atomically (.partial, then
os.replace), under a lock: moves come from several threads. Only its own
daemon writes it (one per folder, FileLock).
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)


class JsonInstrumentStates:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._records: Dict[str, Dict[str, Any]] = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        try:
            found = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            logger.error(f"{self.path} is not read, nothing kept is applied: {e}")
            return {}
        if not isinstance(found, dict):
            logger.error(f"{self.path} holds no records, nothing kept is applied")
            return {}
        return {key: value for key, value in found.items() if isinstance(value, dict)}

    def get(self, instrument_id: str) -> Optional[Mapping[str, Any]]:
        with self._lock:
            record = self._records.get(instrument_id)
            return None if record is None else dict(record)

    def put(self, instrument_id: str, record: Mapping[str, Any]) -> None:
        with self._lock:
            self._records[instrument_id] = dict(record)
            text = json.dumps(self._records, indent=2, sort_keys=True)
            partial = self.path.with_suffix(".partial")
            try:
                partial.write_text(text, encoding="utf-8")
                os.replace(partial, self.path)
            except OSError as e:
                logger.error(f"{self.path}: {instrument_id} is not kept: {e}")
