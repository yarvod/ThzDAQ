"""DISABLED: not imported or registered; kept for the rewrite of the Pfeiffer driver.

Pfeiffer Vacuum protocol parameters: number, name, data type, access, description.

Generated from the legacy settings.PFEIFFER_PARAMETERS; 340 is u_expo_new (was 7).
"""

from typing import Dict, NamedTuple


class Parameter(NamedTuple):
    number: int
    name: str
    data_type: int
    access: str  # R, W or RW
    description: str


PARAMETERS: Dict[int, Parameter] = {
    1: Parameter(1, "Heating", 0, "RW", "Heating"),
    2: Parameter(2, "Standby", 0, "RW", "Standby"),
    4: Parameter(4, "RUTimeCtrl", 0, "RW", "Run-up time control"),
    9: Parameter(9, "ErrorAckn", 0, "W", "Error acknowledgement"),
    10: Parameter(10, "PumpgStatn", 0, "RW", "Pumping station"),
    12: Parameter(12, "EnableVent", 0, "RW", "Enable venting"),
    17: Parameter(
        17, "CfgSpdSwPt", 7, "RW", "Configuration rotation speed switch point"
    ),
    19: Parameter(19, "Cfg_DO2", 7, "RW", "Configuration output DO2"),
    23: Parameter(23, "MotorPump", 0, "RW", "Motor pump"),
    24: Parameter(24, "Cfg_DO1", 7, "RW", "Configuration output DO1"),
    25: Parameter(25, "OpMode_BKP", 7, "RW", "Operation mode backing pump"),
    26: Parameter(26, "SpdSetMode", 7, "RW", "Rotation speed setting mode"),
    27: Parameter(27, "GasMode", 7, "RW", "Gas mode"),
    30: Parameter(30, "VentMode", 7, "RW", "Venting mode"),
    35: Parameter(35, "Cfg_Acc_A1", 7, "RW", "Configuration accessory connection A1"),
    36: Parameter(36, "Cfg_Acc_B1", 7, "RW", "Configuration accessory connection B1"),
    37: Parameter(37, "Cfg_Acc_A2", 7, "RW", "Configuration accessory connection A2"),
    38: Parameter(38, "Cfg_Acc_B2", 7, "RW", "Configuration accessory connection B2"),
    50: Parameter(50, "SealingGas", 0, "RW", "Sealing gas"),
    55: Parameter(55, "Cfg_AO1", 7, "RW", "Configuration output AO1"),
    60: Parameter(60, "CtrlViaInt", 7, "RW", "Control via interface"),
    61: Parameter(61, "IntSelLckd", 0, "RW", "Interface selection locked"),
    62: Parameter(62, "Cfg_DI1", 7, "RW", "Configuration input DI1"),
    63: Parameter(63, "Cfg_DI2", 7, "RW", "Configuration input DI2"),
    300: Parameter(300, "RemotePrio", 0, "R", "Remote priority"),
    302: Parameter(302, "SpdSwPtAtt", 0, "R", "Rotation speed switch point attained"),
    303: Parameter(303, "Error_code", 4, "R", "Error code"),
    304: Parameter(
        304, "OvTempElec", 0, "R", "Excess temperature electronic drive unit"
    ),
    305: Parameter(305, "OvTempPump", 0, "R", "Excess temperature pump"),
    306: Parameter(306, "SetSpdAtt", 0, "R", "Set rotation speed attained"),
    307: Parameter(307, "PumpAccel", 0, "R", "Pump accelerates"),
    308: Parameter(308, "SetRotSpd", 1, "R", "Set rotation speed (Hz)"),
    309: Parameter(309, "ActualSpd", 1, "R", "Active rotation speed (Hz)"),
    310: Parameter(310, "DrvCurrent", 2, "R", "Drive current (A)"),
    311: Parameter(311, "OpHrsPump", 1, "R", "Operating hours pump (h)"),
    312: Parameter(312, "Fw_version", 4, "R", "Firmware version electronic drive unit"),
    313: Parameter(313, "DrvVoltage", 2, "R", "Drive voltage (V)"),
    314: Parameter(
        314, "OpHrsElec", 1, "R", "Operating hours electronic drive unit (h)"
    ),
    315: Parameter(315, "Nominal_Spd", 1, "R", "Nominal rotation speed (Hz)"),
    316: Parameter(316, "DrvPower", 1, "R", "Drive power (W)"),
    319: Parameter(319, "PumpCylces", 1, "R", "Pump cycles"),
    326: Parameter(326, "TempElec", 1, "R", "Temperature electronic (°C)"),
    330: Parameter(330, "TempPmpBot", 1, "R", "Temperature pump bottom part (°C)"),
    336: Parameter(336, "AccelDecel", 1, "R", "Acceleration / Deceleration (rpm/s)"),
    340: Parameter(340, "Pressure", 10, "R", "Active pressure value (mbar)"),
    342: Parameter(342, "TempBearng", 1, "R", "Temperature bearing (°C)"),
    346: Parameter(346, "TempMotor", 1, "R", "Temperature motor (°C)"),
    349: Parameter(349, "ElecName", 4, "R", "Name of electronic drive unit"),
    350: Parameter(350, "Ctr_Name", 4, "R", "Type of display and control unit"),
    351: Parameter(351, "Ctr_Software", 4, "R", "Software of display and control unit"),
    354: Parameter(354, "HW_Version", 4, "R", "Hardware version electronic drive unit"),
    360: Parameter(360, "ErrHist1", 4, "R", "Error code history, pos. 1"),
    361: Parameter(361, "ErrHist2", 4, "R", "Error code history, pos. 2"),
    362: Parameter(362, "ErrHist3", 4, "R", "Error code history, pos. 3"),
    363: Parameter(363, "ErrHist4", 4, "R", "Error code history, pos. 4"),
    364: Parameter(364, "ErrHist5", 4, "R", "Error code history, pos. 5"),
    365: Parameter(365, "ErrHist6", 4, "R", "Error code history, pos. 6"),
    366: Parameter(366, "ErrHist7", 4, "R", "Error code history, pos. 7"),
    367: Parameter(367, "ErrHist8", 4, "R", "Error code history, pos. 8"),
    368: Parameter(368, "ErrHist9", 4, "R", "Error code history, pos. 9"),
    369: Parameter(369, "ErrHist10", 4, "R", "Error code history, pos. 10"),
    397: Parameter(397, "SetRotSpd_rpm", 1, "R", "Set rotation speed (rpm)"),
    398: Parameter(398, "ActualSpd_rpm", 1, "R", "Actual rotation speed (rpm)"),
    399: Parameter(399, "NominalSpd_rpm", 1, "R", "Nominal rotation speed (rpm)"),
    700: Parameter(700, "RUTimeSVal", 1, "RW", "Set value run-up time (min)"),
    701: Parameter(701, "SpdSwPt1", 1, "RW", "Rotation speed switch point 1 (%)"),
    707: Parameter(707, "SpdSVal", 2, "RW", "Set value in rot. speed setting mode (%)"),
    708: Parameter(708, "PwrSVal", 7, "RW", "Set value power consumption (%)"),
    710: Parameter(
        710,
        "SwOff BKP",
        1,
        "RW",
        "Switching off threshold backing pump in intermittend mode (W)",
    ),
    711: Parameter(
        711,
        "SwOn BKP",
        1,
        "RW",
        "Switching on threshold backing pump in intermittend mode (W)",
    ),
    717: Parameter(
        717, "StdbySVal", 2, "RW", "Set value rotation speed at standby (%)"
    ),
    719: Parameter(719, "SpdSwPt2", 1, "RW", "Rotation speed switch point 2 (%)"),
    720: Parameter(
        720, "VentSpd", 7, "RW", "Venting rot. speed at delayed venting (%)"
    ),
    721: Parameter(721, "VentTime", 1, "RW", "Venting time at delayed venting (s)"),
    738: Parameter(738, "Gaugetype", 4, "RW", "Type of pressure gauge"),
    740: Parameter(
        740, "Pressure_gauge", 10, "R", "Pressure of a connected gauge (hPa)"
    ),
    777: Parameter(
        777, "NomSpdConf", 1, "RW", "Nominal rotation speed confirmation (Hz)"
    ),
    794: Parameter(794, "Param_set", 7, "RW", "Parameterset"),
    795: Parameter(795, "Servicelin", 7, "RW", "Insert service line"),
    797: Parameter(797, "RS485Adr", 1, "RW", "RS485 device address"),
}
BY_NAME: Dict[str, Parameter] = {p.name: p for p in PARAMETERS.values()}
