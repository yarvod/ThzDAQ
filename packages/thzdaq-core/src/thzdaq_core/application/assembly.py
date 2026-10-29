"""The use cases of a bench, assembled: every handler with what it needs, listed
explicitly, and the services that run on their own (polling) to stop at the end."""

from dataclasses import dataclass

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.dispatch import Dispatcher
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.handlers import devices, state
from thzdaq_core.application.polling import Polling
from thzdaq_core.application.values import KnownValues


@dataclass
class Assembled:
    dispatcher: Dispatcher
    events: EventBus
    polling: Polling

    def close(self) -> None:
        self.polling.stop()


def assemble(bench: Bench) -> Assembled:
    events = EventBus()
    known = KnownValues()
    access = DeviceAccess(bench, known, events)
    polling = Polling(access, events)
    dispatcher = Dispatcher(
        (
            devices.ListDevices(bench),
            devices.DescribeDevice(bench, access),
            devices.ReadDevice(access),
            devices.SetQuantity(access),
            state.SubscribePoll(polling),
            state.CancelPoll(polling),
            state.GetSnapshot(events, known),
        )
    )
    return Assembled(dispatcher, events, polling)
