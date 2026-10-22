"""thzdaq-station: manage and check bench profiles from the command line."""

import argparse
import sys
from typing import List, Optional

from thzdaq_instruments import InstrumentError
from thzdaq_instruments.capabilities import ALL_CAPABILITIES, Identifiable

from thzdaq_core.station.legacy import import_legacy_settings
from thzdaq_core.station.station import Station
from thzdaq_core.station.storage import dump_station, load_station, save_station


def capability_names(device) -> List[str]:
    return [
        c.__name__
        for c in ALL_CAPABILITIES
        if c is not Identifiable and isinstance(device, c)
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
    station = Station(config, simulate=True)
    print(f"{config.name}: {config.description}".rstrip(": "))
    for instrument_id, spec in config.instruments.items():
        where = spec.connection.link_key if spec.connection else "-"
        sim = " [sim]" if spec.simulate else ""
        print(f"{instrument_id:30} {spec.driver:18} {where}{sim}  {spec.title}")
        if spec.settings:
            values = ", ".join(f"{k}={v}" for k, v in spec.settings.items())
            print(f"  {'settings':28} {values}")
        for info in station.devices():
            if info.instrument != instrument_id or info.kind == "instrument":
                continue
            caps = [c.__name__ for c in info.capabilities if c is not Identifiable]
            print(f"  {info.ref:28} {info.kind:18} {info.title}: {', '.join(caps)}")
    return 0


def cmd_check(args) -> int:
    failures = 0
    with Station.load(args.profile, simulate=args.simulate) as station:
        refs = args.devices or [info.ref for info in station.devices()]
        for ref in refs:
            try:
                device = station.device(ref)
            except InstrumentError as e:
                failures += 1
                print(f"FAIL {ref}: {e}")
                continue
            print(f"ok   {ref}: {', '.join(capability_names(device)) or '-'}")
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

    show = commands.add_parser("show", help="print instruments and devices")
    show.add_argument("profile")
    show.set_defaults(func=cmd_show)

    check = commands.add_parser("check", help="open devices and report capabilities")
    check.add_argument("profile")
    check.add_argument("--simulate", action="store_true")
    check.add_argument("--devices", nargs="*", help="device refs, default: all")
    check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except InstrumentError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
