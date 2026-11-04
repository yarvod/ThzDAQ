"""Names of the built-in procedures: clients start a procedure by its name, and the
core's procedure classes take their names from here.

A name is "<group>.<procedure>"; the group sorts procedures in menus. The
monitor's rules of what is watched and where it is drawn are here too: the
monitor applies them, and a client choosing what to watch or plotting what a
device dock reads applies the same ones.
"""

from typing import Any, Iterable, List, Optional, Tuple

SIS = "sis"
IF = "if"
TWO_SB = "two_sb"
MONITOR = "monitor"
GRID = "grid"

IV_CURVE = f"{SIS}.iv_curve"
PV_CURVE = f"{SIS}.pv_curve"
Y_FACTOR_VOLTAGE = f"{SIS}.y_factor_voltage"
REFLECTION = f"{SIS}.reflection"
SHOT_NOISE = f"{SIS}.shot_noise"
CL_CURVE = f"{SIS}.cl_curve"
DEMAGNETIZE = f"{SIS}.demagnetize"
IF_HOT_COLD = f"{IF}.hot_cold"
TWO_SB_IF_BALANCE = f"{TWO_SB}.if_balance"
TWO_SB_PUMP_BALANCE = f"{TWO_SB}.pump_balance"
TWO_SB_SRR = f"{TWO_SB}.srr"
TWO_SB_TN = f"{TWO_SB}.tn"
TWO_SB_OPTIMIZATION = f"{TWO_SB}.optimization"
MONITOR_TIME = f"{MONITOR}.time"
GRID_CURRENT_ANGLE = f"{GRID}.current_angle"


def group_of(name: str) -> str:
    """sis.iv_curve -> sis"""
    return name.split(".", 1)[0]


# What the monitor watches: "<ref>" or "<ref>/<quantity key>"; a column's source too
KEY_SEPARATOR = "/"

# The time graph of each unit
UNIT_PLOTS = {
    "dBm": "P-t",
    "K": "T-t",
    "V": "V-t",
    "A": "I-t",
    "Pa": "p-t",
    "Hz": "f-t",
}
COIL_PLOT = "Coil-t"  # mA of a coil, not the µA of a SIS on I-t
OTHER_PLOT = "Value-t"
COIL_KEYS = ("current_set", "coil_current")


def split_entry(entry: str) -> Tuple[str, Optional[str]]:
    """ "sis_bias_1/voltage" -> ("sis_bias_1", "voltage"); "power_meter_1" -> (ref, None)."""
    ref, _, key = entry.partition(KEY_SEPARATOR)
    return ref, key or None


def entry(ref: str, key: str) -> str:
    """("sis_bias_1", "voltage") -> "sis_bias_1/voltage": a quantity of a device
    in one text, as the monitor watches it and a column names its source."""
    return f"{ref}{KEY_SEPARATOR}{key}"


# The rules take quantities as described (instruments' Quantity, or QuantityInfo)
def monitor_quantities(quantities: Iterable[Any]) -> List[Any]:
    """Quantities worth watching: numeric readings, not configuration."""
    return [
        q
        for q in quantities
        if q.readable and q.kind in ("float", "int") and not q.persistent
    ]


def default_quantities(quantities: Iterable[Any]) -> List[Any]:
    """Read when a device is watched without a choice: measured values with a
    unit, or the readable setpoints when nothing is measured (a SIS coil
    current). A value without a unit (the NRX reading in its display unit) can
    be chosen by hand."""
    candidates = [q for q in monitor_quantities(quantities) if q.unit]
    return [q for q in candidates if not q.settable] or candidates


def plot_for(quantity: Any) -> str:
    """The time graph of a quantity, by its unit."""
    if quantity.unit == "A" and quantity.key in COIL_KEYS:
        return COIL_PLOT
    return UNIT_PLOTS.get(quantity.unit, OTHER_PLOT)
