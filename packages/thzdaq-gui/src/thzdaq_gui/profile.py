"""The station profile as get_station gives it: a dict in the format of its YAML
file (version 2). Setup and the device docks change a copy and hand it to
update_station, which checks, saves and applies it.
"""

import copy
from typing import Any, Dict, List, Mapping, Optional, Tuple

from thzdaq_api.station import (  # noqa: F401 (the format's keys, for its users)
    CHANNEL,
    CONNECTION,
    DEVICES,
    DRIVER,
    HARDWARE_PROTECTION,
    INSTRUMENTS,
    KIND,
    LIMITS,
    METADATA,
    SAFE_STATE,
    SAFETY,
    SETTINGS,
    SIMULATE,
    TITLE,
    free_id,
)

Profile = Dict[str, Any]
Entry = Dict[str, Any]  # an instrument or a device of the profile

# A limit of a quantity: its keys and how a table heads them
LIMIT_KEYS = {
    "min": "Min",
    "max": "Max",
    "warn_min": "Warn min",
    "warn_max": "Warn max",
    "step": "Step",
    "rate": "Rate, /s",
}


def instruments(profile: Mapping[str, Any]) -> Dict[str, Entry]:
    return profile.get(INSTRUMENTS) or {}


def devices(instrument: Mapping[str, Any]) -> Dict[str, Entry]:
    return instrument.get(DEVICES) or {}


def find_device(
    profile: Mapping[str, Any], device_id: str
) -> Optional[Tuple[str, Entry]]:
    """(instrument id, entry) of a configured device."""
    for instrument_id, instrument in instruments(profile).items():
        if device_id in devices(instrument):
            return instrument_id, devices(instrument)[device_id]
    return None


def next_id(profile: Mapping[str, Any], prefix: str) -> str:
    """A free id like power_supply_3 or sis_bias_2."""
    taken: List[str] = list(instruments(profile))
    for instrument in instruments(profile).values():
        taken.extend(devices(instrument))
    return free_id(taken, prefix)


def changed(profile: Mapping[str, Any]) -> Profile:
    """A copy to change, every section there to write into."""
    edited = copy.deepcopy(dict(profile))
    edited.setdefault(INSTRUMENTS, {})
    for instrument in edited[INSTRUMENTS].values():
        instrument.setdefault(DEVICES, {})
    return edited
