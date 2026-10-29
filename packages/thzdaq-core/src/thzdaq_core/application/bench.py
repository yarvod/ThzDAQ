"""The bench the use cases work on: the station loaded now (another profile may
replace it), the file it came from and the lanes its instruments' jobs run in."""

from typing import Any, Callable, Optional

from thzdaq_api.errors import ErrorCode, LabError

from thzdaq_core.application.lanes import Deliver, Lanes
from thzdaq_core.domain.errors import StationError
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
