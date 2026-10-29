"""Operations on the profile, the drivers it can use and the connections."""

from typing import Tuple

from thzdaq_api import station as api

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


class ListDrivers(Handler[api.ListDrivers, Tuple[api.DriverInfo, ...]]):
    operation = api.ListDrivers

    def __init__(self, station: StationService):
        self.station = station

    def handle(self, args, origin):
        return self.station.drivers()


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
