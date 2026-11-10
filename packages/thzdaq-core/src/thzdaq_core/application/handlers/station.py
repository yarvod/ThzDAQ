"""Operations on the profile, the drivers it can use and the connections."""

from typing import Any, Dict, Tuple

from thzdaq_api import station as api
from thzdaq_api.operation import Rights

from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.station import StationService


class GetStation(Handler[api.GetStation, api.StationProfile]):
    operation = api.GetStation

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.profile()


class LoadStation(Handler[api.LoadStation, api.StationProfile]):
    operation = api.LoadStation

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.load(args.path)


class NewStation(Handler[api.NewStation, api.StationProfile]):
    operation = api.NewStation

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.new(args.path, args.title)


class UpdateStation(Handler[api.UpdateStation, api.StationProfile]):
    operation = api.UpdateStation

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.update(args.profile)


class DeclareInstrument(Handler[api.DeclareInstrument, str]):
    """A change of the profile, which a person allows; an instrument the
    profile has as declared changes nothing and needs no more than a look."""

    operation = api.DeclareInstrument

    def __init__(self, station: StationService):
        self.station = station

    def _declared(self, args):
        return self.station.declaration(args.instrument, args.driver, args.connection)

    def handle(self, args, origin):
        return self.station.declare(self._declared(args))

    def needs(self, args):
        if self._declared(args).change == api.KEPT:
            return Rights.READ
        return self.operation.rights

    def approval(self, args, origin):
        return self._declared(args).ask()


class ListDrivers(Handler[api.ListDrivers, Tuple[api.DriverInfo, ...]]):
    operation = api.ListDrivers

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.drivers()


class ListConnectionKinds(
    Handler[api.ListConnectionKinds, Tuple[api.ConnectionKindInfo, ...]]
):
    operation = api.ListConnectionKinds

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.connection_kinds()


class ConnectInstrument(Handler[api.ConnectInstrument, str]):
    operation = api.ConnectInstrument

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.connect(args.instrument)


class GetSisCalibration(Handler[api.GetSisCalibration, Dict[str, Any]]):
    operation = api.GetSisCalibration

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.sis_calibration(args.ref)


class SetSisCalibration(Handler[api.SetSisCalibration, api.StationProfile]):
    operation = api.SetSisCalibration

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.set_sis_calibration(args.ref, args.coefficients)


class ListConnections(Handler[api.ListConnections, Tuple[api.ConnectionInfo, ...]]):
    operation = api.ListConnections

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.connections()


class ResetConnection(Handler[api.ResetConnection, bool]):
    operation = api.ResetConnection

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.reset_connection(args.key)
