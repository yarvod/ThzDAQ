"""The bench the use cases work on: the station loaded now (another profile may
replace it), the file it came from and the lanes its instruments' jobs run in."""

from typing import Any, Callable, List, Optional

from thzdaq_api.errors import ErrorCode, LabError

from thzdaq_api.lanes import Deliver, Lanes
from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.station.config import InstrumentConfig
from thzdaq_core.domain.station.station import DeviceInfo, Station


class Bench:
    def __init__(self, station: Station, lanes: Lanes, path: Optional[str] = None):
        self.station = station
        self.lanes = lanes
        self.path = path

    def replace(self, station: Station, path: Optional[str]) -> None:
        """Work with another station; the old one closes its instruments."""
        old, self.station, self.path = self.station, station, path
        old.close()

    def info(self, ref: str) -> DeviceInfo:
        try:
            return self.station.info(ref)
        except StationError:
            raise LabError(
                ErrorCode.NOT_FOUND, f"No device {ref!r}", "list_devices names them"
            ) from None

    def instrument(self, instrument_id: str) -> InstrumentConfig:
        """An instrument of the profile; an unknown one is NOT_FOUND (a device
        on one names its instrument)."""
        spec = self.station.config.instruments.get(instrument_id)
        if spec is None:
            raise LabError(
                ErrorCode.NOT_FOUND,
                f"No instrument {instrument_id!r}",
                self._instrument_of(instrument_id),
            )
        return spec

    def _instrument_of(self, ref: str) -> str:
        try:
            owner = self.station.info(ref).instrument
        except StationError:
            return "get_station lists them"
        return f"{ref} is a device on the instrument {owner}"

    def raw_parts(self, instrument_id: str) -> List[str]:
        """The devices a raw command to the instrument may change: every one on
        it. NOT_FOUND for an unknown instrument, NOT_ALLOWED for one that takes
        no raw commands."""
        self.instrument(instrument_id)
        if not self.station.takes_raw(instrument_id):
            raise LabError(
                ErrorCode.NOT_ALLOWED,
                f"{instrument_id} takes no raw commands",
                "its driver does not talk text (HTTP, Modbus)",
            )
        return self.station.parts_of(instrument_id)

    def raw(self, instrument_id: str, command: str, answer: bool) -> Optional[str]:
        """A raw command in the instrument's lane, its answer when one is read;
        waits for it."""
        spec = self.instrument(instrument_id)
        return self.lanes.call(
            instrument_id,
            lambda: self.station.raw(instrument_id).send_raw(command, answer),
            label=spec.title or instrument_id,
        )

    def run(self, ref: str, job: Callable[[Any], Any]) -> Any:
        """job(device), in the lane of the device's instrument; waits for it."""
        info = self.info(ref)
        return self.lanes.call(
            info.instrument, lambda: job(self.station.device(ref)), label=info.title
        )

    def submit(self, ref: str, job: Callable[[Any], Any], deliver: Deliver) -> None:
        """job(device) in the device's lane, without waiting: deliver(result,
        error) is called in the lane when it ends."""
        info = self.info(ref)
        self.lanes.submit(
            info.instrument,
            lambda: job(self.station.device(ref)),
            deliver,
            label=info.title,
        )
