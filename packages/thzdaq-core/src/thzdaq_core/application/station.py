"""The profile of the bench: shown, edited, replaced; its instruments opened, its
shared connections.

An edited profile is checked, saved to its file and applied (only instruments
whose setup changed reopen); another profile replaces the station, which is
refused while measurements run. Either way clients hear station_changed.
"""

import copy
from typing import Any, Dict, Mapping, Tuple

from thzdaq_api import station as api
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import StationChanged

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.describe import (
    connection_info,
    connection_kinds,
    driver_info,
)
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.ports import ProfileRepository
from thzdaq_core.application.runs import Runs
from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.sis.calibration import (
    CALIBRATION_KEY,
    WRITE_CALIBRATION,
    calibration_for,
    normalize_sis_calibration,
)
from thzdaq_core.domain.station.config import DeviceConfig, StationConfig
from thzdaq_core.domain.station.profile import station_from_dict, station_to_dict
from thzdaq_core.domain.station.station import Station, touched
from thzdaq_instruments.capabilities import Identifiable, capabilities_of


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
        self._refuse_disturbing(config)
        if self.bench.path is not None:
            self.profiles.save(config, self.bench.path)
        self.bench.station.reconfigure(config)
        self._changed()
        return self.profile()

    def drivers(self) -> Tuple[api.DriverInfo, ...]:
        return tuple(driver_info(info) for info in self.bench.station.registry.all())

    def connection_kinds(self) -> Tuple[api.ConnectionKindInfo, ...]:
        return connection_kinds()

    def connect(self, instrument_id: str) -> str:
        """Open an instrument in its lane and ask who it is."""
        station = self.bench.station
        spec = station.config.instruments.get(instrument_id)
        if spec is None:
            raise LabError(
                ErrorCode.NOT_FOUND,
                f"No instrument {instrument_id!r}",
                "get_station lists them",
            )

        def identify() -> str:
            instrument = station.instrument(instrument_id)
            if Identifiable in capabilities_of(type(instrument)):
                return instrument.identify()
            return "opened"

        return self.bench.lanes.call(
            instrument_id, identify, label=spec.title or instrument_id
        )

    def sis_calibration(self, ref: str) -> Dict[str, Any]:
        spec = self._calibrated(ref)
        return calibration_for(spec.channel, spec.metadata.get(CALIBRATION_KEY))

    def set_sis_calibration(
        self, ref: str, coefficients: Mapping[str, Any]
    ) -> api.StationProfile:
        self._calibrated(ref)
        try:
            checked = normalize_sis_calibration(coefficients)
        except ValueError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        config = copy.deepcopy(self.bench.station.config)
        config.find_device(ref)[1].metadata[CALIBRATION_KEY] = checked
        return self.update(station_to_dict(config))

    def _calibrated(self, ref: str) -> DeviceConfig:
        """The profile entry of a device that writes a calibration."""
        station = self.bench.station
        self.bench.info(ref)  # an unknown device is NOT_FOUND
        found = station.config.find_device(ref)
        if found is None or WRITE_CALIBRATION not in [
            action.key for action in station.actions(ref)
        ]:
            raise LabError(ErrorCode.NOT_ALLOWED, f"{ref} keeps no SIS calibration")
        return found[1]

    def connections(self) -> Tuple[api.ConnectionInfo, ...]:
        return tuple(connection_info(c) for c in self.bench.station.connections())

    def reset_connection(self, key: Tuple) -> bool:
        return self.bench.station.reset_connection(tuple(key))

    def _refuse_disturbing(self, config: StationConfig) -> None:
        """An edit that reopens, removes or sets up anew what a running
        measurement uses (or changes its limits) waits for it."""
        station = self.bench.station
        changed = touched(station.config, config)
        users: Dict[int, str] = {}
        for lease in self.runs.leases.all():
            ids = {lease.device, station.info(lease.device).instrument}
            if ids & changed:
                users[lease.owner] = f"#{lease.owner} {lease.title} ({lease.device})"
        if users:
            raise LabError(
                ErrorCode.NOT_ALLOWED,
                f"Running measurements use what the edit changes: "
                f"{', '.join(users.values())}",
                "stop them first, or change what they do not use",
            )

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
