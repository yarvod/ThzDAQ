"""thzdaq devices, device, read, set, call, safe, connections: the devices of the
bench, what they read and take, their actions, the safe state, the shared
connections. A value is typed with its unit ("2.3mV", "223GHz"); the daemon
parses it, checks it against the limits and sets it in steps where they ask."""

from typing import Dict, List, Sequence

from thzdaq_api.devices import (
    CallAction,
    DescribeDevice,
    DeviceDescription,
    ListDevices,
    QuantityInfo,
    ReadDevice,
    SafeState,
    SetQuantity,
    Trace,
)
from thzdaq_api.station import ListConnections, ResetConnection

from thzdaq_cli import show
from thzdaq_cli.client import FAILED, OK, Client, Mistyped


def add(commands) -> None:
    commands.add_parser("devices", help="the devices of the bench").set_defaults(
        run=list_devices
    )
    device = commands.add_parser("device", help="what a device reads, takes, does")
    device.add_argument("ref")
    device.set_defaults(run=describe)
    read = commands.add_parser("read", help="read a device")
    read.add_argument("ref")
    read.add_argument("keys", nargs="*", help="quantities; all it reads by default")
    read.set_defaults(run=read_device)
    set_ = commands.add_parser(
        "set", help="set a quantity: thzdaq set sis_bias_1 voltage_set 2.3mV"
    )
    set_.add_argument("ref")
    set_.add_argument("key")
    set_.add_argument("value", help="with its unit, or SI; on/off for switches")
    set_.add_argument(
        "--share", action="store_true", help="also while a measurement sweeps it"
    )
    set_.set_defaults(run=set_quantity)
    call = commands.add_parser("call", help="an action: thzdaq call chopper_1 to_hot")
    call.add_argument("ref")
    call.add_argument("action")
    call.add_argument("arguments", nargs="*", metavar="NAME=VALUE")
    call.add_argument(
        "--share", action="store_true", help="also while a measurement sweeps it"
    )
    call.set_defaults(run=call_action)
    safe = commands.add_parser("safe", help="set the profile's safe state")
    safe.add_argument(
        "--share", action="store_true", help="also where measurements sweep"
    )
    safe.set_defaults(run=safe_state)
    connections = commands.add_parser("connections", help="shared connections")
    actions = connections.add_subparsers(dest="action", metavar="ACTION")
    reset = actions.add_parser("reset", help="break and reopen one that hangs")
    reset.add_argument("number", type=int, help="as the list numbers it")
    connections.set_defaults(run=list_connections, action=None)


def list_devices(args, client: Client) -> int:
    found = client.call(ListDevices())
    client.out(
        found,
        lambda d: show.table(
            ("device", "type", "title"), [(i.ref, i.type, i.title) for i in d]
        ),
    )
    return OK


def description_text(found: DeviceDescription) -> str:
    device = found.device
    lines = [f"{device.title} ({device.ref}, {device.type}, {device.driver})"]
    quantities = show.table(
        ("quantity", "title", "unit", "", "min", "max"),
        [(q.key, q.title, q.unit, access(q), show.value(q.minimum), show.value(q.maximum))
         for q in found.quantities],
    )  # fmt: skip
    if quantities:
        lines += ["", quantities]
    for action in found.actions:
        arguments = ", ".join(f"{a.key}={a.unit or a.kind}" for a in action.arguments)
        warning = f"  ({action.danger})" if action.danger else ""
        lines.append(f"action {action.key} {arguments}{warning}".rstrip())
    for setting in found.settings:
        lines.append(f"setting {setting.key} {setting.unit} (in the profile)")
    return "\n".join(lines)


def access(quantity: QuantityInfo) -> str:
    return ("r" if quantity.readable else "-") + ("w" if quantity.settable else "-")


def describe(args, client: Client) -> int:
    client.out(client.call(DescribeDevice(ref=args.ref)), description_text)
    return OK


def read_device(args, client: Client) -> int:
    units = {
        q.key: q.unit for q in client.call(DescribeDevice(ref=args.ref)).quantities
    }
    reading = client.call(ReadDevice(ref=args.ref, keys=tuple(args.keys) or None))
    client.out(
        reading,
        lambda r: show.table(
            ("quantity", "value"),
            [(key, show.value(v, units.get(key, ""))) for key, v in r.values.items()],
        ),
    )
    return OK


def quantity(client: Client, ref: str, key: str) -> QuantityInfo:
    found = client.call(DescribeDevice(ref=ref)).quantities
    return next((q for q in found if q.key == key), QuantityInfo(key, key))


def set_quantity(args, client: Client) -> int:
    found = quantity(client, args.ref, args.key)
    if found.danger and not client.ask(f"{found.danger}. Set {args.ref} {args.key}?"):
        return FAILED
    done = client.shared(
        lambda share: client.call(
            SetQuantity(
                ref=args.ref, key=args.key, value=args.value, share=share or args.share
            )
        )
    )
    if done is None:
        return FAILED
    client.out(done, lambda d: f"{d.ref} {d.key} = {show.value(d.value, found.unit)}")
    return OK


def assignments(given: Sequence[str]) -> Dict[str, str]:
    """NAME=VALUE pairs as typed; the daemon parses the values."""
    found = {}
    for text in given:
        name, sign, value = text.partition("=")
        if not sign or not name:
            raise Mistyped(f"{text!r} is not NAME=VALUE")
        found[name] = value
    return found


def call_action(args, client: Client) -> int:
    arguments = assignments(args.arguments)
    actions = client.call(DescribeDevice(ref=args.ref)).actions
    danger = next((a.danger for a in actions if a.key == args.action), "")
    if danger and not client.ask(f"{danger}. {args.action} on {args.ref}?"):
        return FAILED
    done = client.shared(
        lambda share: client.call(
            CallAction(
                ref=args.ref,
                action=args.action,
                arguments=arguments,
                share=share or args.share,
            )
        )
    )
    if done is None:
        return FAILED
    client.out(done, lambda d: result_text(d.result))
    return OK


def result_text(result) -> str:
    if isinstance(result, Trace):
        points, frequency = len(result.frequency), result.frequency
        name = f" {result.parameter}" if result.parameter else ""
        span = f", {frequency[0]:.6g}..{frequency[-1]:.6g} Hz" if points else ""
        return f"trace{name} of {points} points{span} (--json gives it all)"
    return "done" if result is None else show.value(result)


def safe_state(args, client: Client) -> int:
    if not client.ask("Set every value of the profile's safe state now?"):
        return FAILED
    done = client.call(SafeState(share=args.share))
    client.out(
        done,
        lambda d: show.table(
            ("device", "quantity", "value", "result"),
            [(v.ref, v.key, show.value(v.value), v.error or "set") for v in d],
        )
        or "the profile names no safe state",
    )
    return FAILED if any(value.error for value in done) else OK


def list_connections(args, client: Client) -> int:
    found = client.call(ListConnections())
    if args.action == "reset":
        if not 1 <= args.number <= len(found):
            print(f"thzdaq: no connection {args.number}; thzdaq connections lists them")
            return FAILED
        chosen = found[args.number - 1]
        reopened = client.call(ResetConnection(key=chosen.key))
        print(f"{chosen.label}: {'reset' if reopened else 'was not open'}")
        return OK
    rows: List[tuple] = [
        (number, c.label, "broken" if c.broken else "open" if c.open else "closed",
         ", ".join(c.instruments))
        for number, c in enumerate(found, 1)
    ]  # fmt: skip
    client.out(
        found,
        lambda _: show.table(("", "connection", "state", "instruments"), rows)
        or "no shared connection",
    )
    return OK
