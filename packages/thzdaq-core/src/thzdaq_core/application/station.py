"""The profile of the bench: shown, edited, replaced; its shared connections.

An edited profile is checked, saved to its file and applied (only instruments
whose setup changed reopen); another profile replaces the station, which is
refused while measurements run. Either way clients hear station_changed.
"""

from typing import Any, Dict, Tuple

from thzdaq_api import station as api
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import StationChanged

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.describe import connection_info, driver_info
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.ports import ProfileRepository
from thzdaq_core.application.runs import Runs
from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.station.config import StationConfig
from thzdaq_core.domain.station.profile import station_from_dict, station_to_dict
from thzdaq_core.domain.station.station import Station


class StationService:
    def __init__(
        self, bench: Bench, profiles: ProfileRepository, runs: Runs, events: EventBus
    ):
        self.bench = bench
        self.profiles = profiles
        self.runs = runs
        self.events = events

    def profile(self) -> api.StationProfile:
        station = self.bench.station
        return api.StationProfile(
            name=station.name,
            path=self.bench.path,
            simulate=station.simulate,
            profile=station_to_dict(station.config),
        )

    def load(self, path: str) -> api.StationProfile:
        self._refuse_while_running()
        try:
            config = self.profiles.load(path)
        except (StationError, OSError) as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        self._replace(config, path)
        return self.profile()

    def new(self, path: str, title: str) -> api.StationProfile:
        self._refuse_while_running()
        config = StationConfig(title)
        try:
            self.profiles.save(config, path)
        except OSError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        self._replace(config, path)
        return self.profile()

    def update(self, data: Dict[str, Any]) -> api.StationProfile:
        try:
            config = station_from_dict(data).validate()
        except StationError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        if self.bench.path is not None:
            self.profiles.save(config, self.bench.path)
        self.bench.station.reconfigure(config)
        self._changed()
        return self.profile()

    def drivers(self) -> Tuple[api.DriverInfo, ...]:
        return tuple(driver_info(info) for info in self.bench.station.registry.all())

    def connections(self) -> Tuple[api.ConnectionInfo, ...]:
        return tuple(connection_info(c) for c in self.bench.station.connections())

    def reset_connection(self, key: Tuple) -> bool:
        return self.bench.station.reset_connection(tuple(key))

    def _refuse_while_running(self) -> None:
        running = self.runs.active()
        if running:
            raise LabError(
                ErrorCode.NOT_ALLOWED,
                f"Measurements run: {', '.join(f'#{r.id} {r.title}' for r in running)}",
                "stop them first",
            )

    def _replace(self, config: StationConfig, path: str) -> None:
        old = self.bench.station
        station = Station(
            config,
            pause=old.pause,
            registry=old.registry,
            pool=old.pool,
            simulate=old.simulate,
            lively=old.lively,
        )
        self.bench.replace(station, path)
        self._changed()

    def _changed(self) -> None:
        self.events.publish(StationChanged(self.bench.station.name, self.bench.path))
