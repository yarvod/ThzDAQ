"""thzdaq station show|load|new: the profile the daemon works with. A profile
is a YAML file, or one of the program's stations/ by its name (lab)."""

from pathlib import Path

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

from thzdaq_api.workspace import is_profile_name

from thzdaq_cli import show
from thzdaq_cli.client import OK, Client


def add(commands) -> None:
    group = commands.add_parser("station", help="the profile of the bench")
    actions = group.add_subparsers(dest="action", required=True, metavar="ACTION")
    actions.add_parser("show", help="its instruments and devices").set_defaults(
        run=show_profile
    )
    load = actions.add_parser(
        "load", help="work with another profile: a YAML file, or a name in stations/"
    )
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


def given(path: str) -> str:
    """A name stays a name (the daemon finds it); a path is this terminal's."""
    return path if is_profile_name(path) else str(Path(path).resolve())


def load_profile(args, client: Client) -> int:
    client.out(client.call(LoadStation(path=given(args.path))), profile_text)
    return OK


def new_profile(args, client: Client) -> int:
    started = NewStation(path=given(args.path), title=args.title)
    client.out(client.call(started), profile_text)
    return OK
