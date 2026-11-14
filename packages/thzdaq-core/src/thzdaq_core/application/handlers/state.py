"""Operations on what the bench knows and tells: the snapshot, polls, leases."""

from typing import Tuple

from thzdaq_api import devices as api
from thzdaq_api import events, leases

from thzdaq_core.application.events import EventBus
from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.polling import Polling
from thzdaq_core.application.runs import Runs
from thzdaq_core.application.values import KnownValues


class GetSnapshot(Handler[events.GetSnapshot, events.Snapshot]):
    operation = events.GetSnapshot

    def __init__(self, events: EventBus, known: KnownValues):
        self.events = events
        self.known = known

    def handle(self, args, origin):
        seq = self.events.seq  # before the values: what comes after is heard
        return events.Snapshot(seq, self.known.all())


class SubscribePoll(Handler[api.SubscribePoll, api.Poll]):
    operation = api.SubscribePoll

    def __init__(self, polling: Polling):
        self.polling = polling

    def handle(self, args, origin):
        return self.polling.subscribe(args.ref, args.interval, args.keys)


class CancelPoll(Handler[api.CancelPoll, None]):
    operation = api.CancelPoll

    def __init__(self, polling: Polling):
        self.polling = polling

    def handle(self, args, origin):
        self.polling.cancel(args.id)


class ListLeases(Handler[leases.ListLeases, Tuple[leases.LeaseInfo, ...]]):
    operation = leases.ListLeases

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        return self.runs.leases_now()
