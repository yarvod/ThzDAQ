"""thzdaq-station: manage and check bench profiles from the command line."""

import argparse
import sys
from typing import List, Optional

from thzdaq_instruments import InstrumentError, default_registry
from thzdaq_instruments.capabilities import ALL_CAPABILITIES, Identifiable

from thzdaq_core.station.legacy import import_legacy_settings
from thzdaq_core.station.ports import ROLE_PROTOCOLS
from thzdaq_core.station.station import Station
from thzdaq_core.station.storage import dump_station, load_station, save_station


def capability_names(port) -> List[str]:
    return [
        c.__name__
        for c in ALL_CAPABILITIES + ROLE_PROTOCOLS
        if c is not Identifiable and isinstance(port, c)
    ]


def cmd_import(args) -> int:
    config, notes = import_legacy_settings(
        args.settings, name=args.name, include_state_defaults=not args.no_defaults
    )
    for note in notes:
        print(f"# {note}", file=sys.stderr)
    if args.output:
        save_station(config, args.output)
        print(f"Saved {args.output}", file=sys.stderr)
    else:
        print(dump_station(config), end="")
    return 0


def cmd_show(args) -> int:
    config = load_station(args.profile)
    registry = default_registry()
    print(f"{config.name}: {config.description}".rstrip(": "))
    print("instruments:")
    for instrument_id, spec in config.instruments.items():
        info = registry.get(spec.driver)
        where = spec.connection.link_key if spec.connection else "-"
        sim = " [sim]" if spec.simulate else ""
        print(f"  {instrument_id:34} {spec.driver:18} {where}{sim}")
        caps = [
            c.__name__
            for c in info.capabilities + info.channel_capabilities
            if c is not Identifiable
        ]
        print(f"  {'':34} {', '.join(caps)}")
    print("roles:")
    for role, spec in config.roles.items():
        part = spec.instrument
        if spec.channel is not None:
            part += f".{spec.accessor}({spec.channel!r})"
        adapter = f" -> {spec.adapter}{spec.options or ''}" if spec.adapter else ""
        print(f"  {role:34} {part}{adapter}")
    return 0


def cmd_check(args) -> int:
    failures = 0
    with Station.load(args.profile, simulate=args.simulate) as station:
        roles = args.roles or list(station.config.roles)
        for role in roles:
            try:
                port = station.role(role)
            except InstrumentError as e:
                failures += 1
                print(f"FAIL {role}: {e}")
                continue
            print(f"ok   {role}: {', '.join(capability_names(port)) or '-'}")
        for instrument_id, identity in station.snapshot()["identities"].items():
            print(f"     {instrument_id}: {identity}")
    return 1 if failures else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="thzdaq-station", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    imp = commands.add_parser(
        "import-legacy", help="convert legacy settings.ini [Configs]"
    )
    imp.add_argument("settings")
    imp.add_argument("-o", "--output")
    imp.add_argument("--name", default="legacy")
    imp.add_argument("--no-defaults", action="store_true", help="skip NRX/YIG/chopper")
    imp.set_defaults(func=cmd_import)

    show = commands.add_parser("show", help="print instruments and roles")
    show.add_argument("profile")
    show.set_defaults(func=cmd_show)

    check = commands.add_parser("check", help="open roles and report capabilities")
    check.add_argument("profile")
    check.add_argument("--simulate", action="store_true")
    check.add_argument("--roles", nargs="*")
    check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except InstrumentError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
