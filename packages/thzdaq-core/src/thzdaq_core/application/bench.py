"""The bench the use cases work on: the station loaded now and the lanes its
instruments' jobs run in."""

from typing import Any, Callable

from thzdaq_api.errors import ErrorCode, LabError

from thzdaq_core.application.lanes import Lanes
from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.station.station import DeviceInfo, Station


class Bench:
    def __init__(self, station: Station, lanes: Lanes):
        self.station = station
        self.lanes = lanes

    def info(self, ref: str) -> DeviceInfo:
        try:
            return self.station.info(ref)
        except StationError:
            raise LabError(
                ErrorCode.NOT_FOUND, f"No device {ref!r}", "list_devices names them"
            ) from None

    def run(self, ref: str, job: Callable[[Any], Any]) -> Any:
        """job(device), in the lane of the device's instrument; waits for it."""
        info = self.info(ref)
        return self.lanes.call(
            info.instrument, lambda: job(self.station.device(ref)), label=info.title
        )
