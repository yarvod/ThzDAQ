"""Types of devices as the GUI names them: an instrument's type comes from its id
(profile ids name the kind of device), a type key becomes a title for menus."""

import re

# Words of type keys written in capitals ("sis_bias" -> "SIS bias")
ACRONYMS = {"sis", "vna", "yig", "if", "lo", "rf", "nrx", "pid", "2sb"}


def id_type(instrument_id: str) -> str:
    """power_supply_3 -> power_supply"""
    return re.sub(r"_\d+$", "", instrument_id)


def type_title(key: str) -> str:
    words = [w.upper() if w in ACRONYMS else w for w in key.split("_") if w]
    if not words:
        return key
    first = words[0]
    return " ".join([first[:1].upper() + first[1:], *words[1:]])
