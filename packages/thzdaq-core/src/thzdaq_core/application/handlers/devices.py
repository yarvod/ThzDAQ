"""Operations on devices: list, describe, read, set, run an action, send a raw
command, go safe."""

from typing import ClassVar, Tuple

import msgspec
from thzdaq_api import devices as api
from thzdaq_api.leases import READ, SHARED
from thzdaq_api.operation import Rights

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.describe import (
    action_info,
    action_result,
    device_info,
    quantity_info,
    setting_info,
)
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_api.scripts import CALL, RAW, SET

from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.processes import ScriptProcesses
from thzdaq_core.application.scripts import Sessions


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
        station = self.bench.station
        guard = station.guard(args.ref)
        return api.DeviceDescription(
            device=device_info(self.bench.info(args.ref), station),
            quantities=tuple(
                quantity_info(q, guard) for q in self.devices.quantities(args.ref)
            ),
            actions=tuple(action_info(a) for a in self.devices.actions(args.ref)),
            settings=tuple(setting_info(s) for s in station.settings(args.ref)),
        )


class ReadDevice(Handler[api.ReadDevice, api.Reading]):
    operation = api.ReadDevice

    def __init__(self, devices: DeviceAccess, sessions: Sessions):
        self.devices = devices
        self.sessions = sessions

    def handle(self, args, origin):
        self.sessions.within(args.session, origin, args.ref, READ)
        return api.Reading(args.ref, self.devices.read(args.ref, args.keys))


class _Change(Handler):
    """A change of a device, which a person may have allowed already: in the
    caller's session, or to its script in advance (as kind: set, call or raw)."""

    kind: ClassVar[str]

    def __init__(
        self, devices: DeviceAccess, sessions: Sessions, scripts: ScriptProcesses
    ):
        self.devices = devices
        self.sessions = sessions
        self.scripts = scripts

    def granted(self, args, origin):
        return self.sessions.grants(
            args.session, origin, args.ref
        ) or self.scripts.allows(origin, self.kind, args.ref)


class SetQuantity(_Change):
    operation = api.SetQuantity
    kind = SET

    def handle(self, args, origin):
        within = self.sessions.within(args.session, origin, args.ref, SHARED)
        value = self.devices.write(
            args.ref, args.key, args.value, origin, args.share, within
        )
        return api.QuantityValue(args.ref, args.key, value)

    def approval(self, args, origin):
        within = self.sessions.found(args.session)
        return self.devices.proposed(args.ref, args.key, args.value, within)

    def amended(self, args, answer):
        """The value the person allowed; the sweep it showed is shared."""
        value = args.value if answer.value is None else answer.value
        return msgspec.structs.replace(args, value=value, share=True)


class CallAction(_Change):
    operation = api.CallAction
    kind = CALL

    def handle(self, args, origin):
        changes = self.devices.action(args.ref, args.action).changes
        mode = SHARED if changes else READ
        within = self.sessions.within(args.session, origin, args.ref, mode)
        result = self.devices.act(
            args.ref, args.action, args.arguments, origin, args.share, within
        )
        return api.ActionResult(args.ref, args.action, action_result(result))

    def needs(self, args):
        """A read (a trace) changes nothing."""
        changes = self.devices.action(args.ref, args.action).changes
        return self.operation.rights if changes else Rights.READ

    def approval(self, args, origin):
        within = self.sessions.found(args.session)
        return self.devices.proposed_action(
            args.ref, args.action, args.arguments, within
        )

    def amended(self, args, answer):
        return msgspec.structs.replace(args, share=True)


class RawCommand(_Change):
    """A query needs fewer rights than a write. A session a person allowed
    does not cover raw writes: only allowing the script raw:<instrument> at
    its start does."""

    operation = api.RawCommand
    kind = RAW

    def handle(self, args, origin):
        mode = READ if args.query else SHARED
        within = self.sessions.within(args.session, origin, args.instrument, mode)
        return self.devices.raw(
            args.instrument, args.command, args.answer, origin, args.share, within
        )

    def needs(self, args):
        return Rights.RAW_QUERY if args.query else self.operation.rights

    def granted(self, args, origin):
        return self.scripts.allows(origin, self.kind, args.instrument)

    def approval(self, args, origin):
        within = self.sessions.found(args.session)
        return self.devices.proposed_raw(args.instrument, args.command, within)

    def amended(self, args, answer):
        return msgspec.structs.replace(args, share=True)


class SafeState(Handler[api.SafeState, Tuple[api.SafeValue, ...]]):
    operation = api.SafeState

    def __init__(self, devices: DeviceAccess):
        self.devices = devices

    def handle(self, args, origin):
        return self.devices.safe_state(origin, args.share)
