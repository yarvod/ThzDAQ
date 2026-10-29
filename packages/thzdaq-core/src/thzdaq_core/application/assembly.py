"""Every handler with what it needs, listed explicitly: the use cases of a bench."""

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.dispatch import Dispatcher
from thzdaq_core.application.handlers import devices


def assemble(bench: Bench) -> Dispatcher:
    access = DeviceAccess(bench)
    return Dispatcher(
        (
            devices.ListDevices(bench),
            devices.DescribeDevice(bench, access),
            devices.ReadDevice(access),
            devices.SetQuantity(access),
        )
    )
