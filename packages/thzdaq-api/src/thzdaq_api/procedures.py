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

# "<group>.<what is measured>_vs_<what is changed>"
CURRENT_VS_VOLTAGE = f"{SIS}.current_vs_voltage"
POWER_VS_VOLTAGE = f"{SIS}.power_vs_voltage"
NOISE_TEMPERATURE_VS_VOLTAGE = f"{SIS}.noise_temperature_vs_voltage"
CURRENT_VS_COIL_CURRENT = f"{SIS}.current_vs_coil_current"
DEMAGNETIZATION = f"{SIS}.demagnetization"
REFLECTION_VS_FREQUENCY = f"{SIS}.reflection_vs_frequency"
CURRENT_VS_GRID_ANGLE = f"{SIS}.current_vs_grid_angle"
AMPLIFIER_NOISE_VS_VOLTAGE = f"{IF}.amplifier_noise_vs_voltage"
NOISE_TEMPERATURE_VS_FREQUENCY = f"{IF}.noise_temperature_vs_frequency"
POWER_VS_FREQUENCY = f"{IF}.power_vs_frequency"
TWO_SB_IF_BALANCE = f"{TWO_SB}.if_balance"
TWO_SB_LO_RF_BALANCE = f"{TWO_SB}.lo_rf_balance"
TWO_SB_SIDEBAND_RATIO = f"{TWO_SB}.sideband_ratio"
TWO_SB_NOISE_TEMPERATURE = f"{TWO_SB}.noise_temperature"
TWO_SB_BIAS_OPTIMIZATION = f"{TWO_SB}.bias_optimization"
MONITOR_VALUES_VS_TIME = f"{MONITOR}.values_vs_time"

# Names procedures had before (old -> current): files measured then, saved
# forms, commands and scripts that still use them
RENAMED = {
    f"{SIS}.iv_curve": CURRENT_VS_VOLTAGE,
    f"{SIS}.pv_curve": POWER_VS_VOLTAGE,
    f"{SIS}.y_factor_voltage": NOISE_TEMPERATURE_VS_VOLTAGE,
    f"{SIS}.cl_curve": CURRENT_VS_COIL_CURRENT,
    f"{SIS}.demagnetize": DEMAGNETIZATION,
    f"{SIS}.reflection": REFLECTION_VS_FREQUENCY,
    f"{SIS}.shot_noise": AMPLIFIER_NOISE_VS_VOLTAGE,
    f"{IF}.hot_cold": NOISE_TEMPERATURE_VS_FREQUENCY,
    f"{TWO_SB}.pump_balance": TWO_SB_LO_RF_BALANCE,
    f"{TWO_SB}.srr": TWO_SB_SIDEBAND_RATIO,
    f"{TWO_SB}.tn": TWO_SB_NOISE_TEMPERATURE,
    f"{TWO_SB}.optimization": TWO_SB_BIAS_OPTIMIZATION,
    "grid.current_angle": CURRENT_VS_GRID_ANGLE,
    "grid.current_vs_angle": CURRENT_VS_GRID_ANGLE,
    f"{MONITOR}.time": MONITOR_VALUES_VS_TIME,
}


def current_name(name: str) -> str:
    """The name a procedure has now: sis.iv_curve -> sis.current_vs_voltage;
    a current or unknown name stays as it is."""
    return RENAMED.get(name, name)


def former_names(name: str) -> List[str]:
    """The names the procedure had before: sis.current_vs_voltage -> [sis.iv_curve]."""
    return [old for old, new in RENAMED.items() if new == name]


def group_of(name: str) -> str:
    """sis.current_vs_voltage -> sis"""
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
