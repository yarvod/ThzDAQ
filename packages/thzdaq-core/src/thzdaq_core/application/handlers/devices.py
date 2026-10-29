"""Operations on devices: list, describe, read, set."""

from typing import Tuple

from thzdaq_api import devices as api

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.describe import device_info, quantity_info
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.handlers import Handler


class ListDevices(Handler[api.ListDevices, Tuple[api.DeviceInfo, ...]]):
    operation = api.ListDevices

    def __init__(self, bench: Bench):
        self.bench = bench

    def handle(self, args, origin):
        station = self.bench.station
        return tuple(device_info(info, station) for info in station.devices())


class DescribeDevice(Handler[api.DescribeDevice, api.DeviceDescription]):
    operation = api.DescribeDevice

    def __init__(self, bench: Bench, devices: DeviceAccess):
        self.bench = bench
        self.devices = devices

    def handle(self, args, origin):
        return api.DeviceDescription(
            device=device_info(self.bench.info(args.ref), self.bench.station),
            quantities=tuple(
                quantity_info(q) for q in self.devices.quantities(args.ref)
            ),
        )


class ReadDevice(Handler[api.ReadDevice, api.Reading]):
    operation = api.ReadDevice

    def __init__(self, devices: DeviceAccess):
        self.devices = devices

    def handle(self, args, origin):
        return api.Reading(args.ref, self.devices.read(args.ref, args.keys))


class SetQuantity(Handler[api.SetQuantity, api.QuantityValue]):
    operation = api.SetQuantity

    def __init__(self, devices: DeviceAccess):
        self.devices = devices

    def handle(self, args, origin):
        value = self.devices.write(args.ref, args.key, args.value)
        return api.QuantityValue(args.ref, args.key, value)
