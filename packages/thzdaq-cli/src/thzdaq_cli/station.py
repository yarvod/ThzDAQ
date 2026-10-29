"""thzdaq station show|load|new: the profile the daemon works with."""

from thzdaq_api.station import (
    DEVICES,
    DRIVER,
    INSTRUMENTS,
    KIND,
    TITLE,
    GetStation,
    LoadStation,
    NewStation,
    StationProfile,
)

from thzdaq_cli import show
from thzdaq_cli.client import OK, Client


def add(commands) -> None:
    group = commands.add_parser("station", help="the profile of the bench")
    actions = group.add_subparsers(dest="action", required=True, metavar="ACTION")
    actions.add_parser("show", help="its instruments and devices").set_defaults(
        run=show_profile
    )
    load = actions.add_parser("load", help="work with another profile (a YAML file)")
    load.add_argument("path")
    load.set_defaults(run=load_profile)
    new = actions.add_parser("new", help="start an empty profile in a new file")
    new.add_argument("path")
    new.add_argument("--title", default="bench")
    new.set_defaults(run=new_profile)


def profile_text(station: StationProfile) -> str:
    lines = [
        show.profile(station.name, station.path)
        + (" simulated" if station.simulate else "")
    ]
    for instrument_id, instrument in (station.profile.get(INSTRUMENTS) or {}).items():
        title, driver = instrument.get(TITLE, ""), instrument[DRIVER]
        lines.append(f"  {instrument_id}: {title} ({driver})")
        for device_id, device in (instrument.get(DEVICES) or {}).items():
            lines.append(f"    {device_id}: {device.get(TITLE, '')} ({device[KIND]})")
    return "\n".join(lines)


def show_profile(args, client: Client) -> int:
    client.out(client.call(GetStation()), profile_text)
    return OK


def load_profile(args, client: Client) -> int:
    client.out(client.call(LoadStation(path=args.path)), profile_text)
    return OK


def new_profile(args, client: Client) -> int:
    client.out(client.call(NewStation(path=args.path, title=args.title)), profile_text)
    return OK
