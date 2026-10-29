"""Names of the built-in procedures: clients start a procedure by its name, and the
core's procedure classes take their names from here.

A name is "<group>.<procedure>"; the group sorts procedures in menus.
"""

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
