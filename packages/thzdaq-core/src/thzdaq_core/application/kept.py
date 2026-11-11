"""What the program keeps of instruments that only it knows (a grid counts its
angle): an instrument with kept state (thzdaq_instruments.state) gets back what
it told last when it opens, and every change it tells is kept, in the
InstrumentStates port (the daemon's state.json).

A record names the driver it was told by: one left by an instrument of another
profile (the id now names another driver) is not applied.
"""

import functools
import logging
from typing import Any, Mapping

from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.state import KeptState

from thzdaq_core.application.ports import InstrumentStates

logger = logging.getLogger(__name__)

DRIVER, STATE = "driver", "state"  # fields of a record


class KeptStates:
    def __init__(self, store: InstrumentStates):
        self.store = store

    def opened(self, instrument_id: str, driver: str, instrument: Instrument) -> None:
        """Station.on_open: what was kept is given back, what changes is kept."""
        if not isinstance(instrument, KeptState):
            return
        record = self.store.get(instrument_id)
        if record is not None:
            self._restore(instrument_id, driver, instrument, record)
        instrument.watch_state(functools.partial(self._keep, instrument_id, driver))

    def _restore(
        self,
        instrument_id: str,
        driver: str,
        instrument: KeptState,
        record: Mapping[str, Any],
    ) -> None:
        if record.get(DRIVER) != driver:
            logger.warning(
                f"{instrument_id}: the state kept by {record.get(DRIVER)!r} "
                f"is not applied to {driver!r}"
            )
            return
        state = record.get(STATE)
        try:
            if not isinstance(state, Mapping):
                raise TypeError(f"{state!r} is no state")
            instrument.restore_state(state)
        except (TypeError, ValueError) as e:
            logger.error(f"{instrument_id}: the kept state is not applied: {e}")
            return
        logger.info(f"{instrument_id}: restored {instrument.kept_state()}")

    def _keep(self, instrument_id: str, driver: str, state: Mapping[str, Any]) -> None:
        self.store.put(instrument_id, {DRIVER: driver, STATE: dict(state)})
