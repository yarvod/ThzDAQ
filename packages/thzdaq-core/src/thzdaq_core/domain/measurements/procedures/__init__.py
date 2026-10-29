"""Built-in procedures. BUILTIN is the list the catalog offers (catalog.py): a new
procedure is added here, explicitly."""

from thzdaq_core.domain.measurements.procedures.grid import GridCurrentAngle
from thzdaq_core.domain.measurements.procedures.if_noise import IFNoise
from thzdaq_core.domain.measurements.procedures.iv_curve import IVCurve
from thzdaq_core.domain.measurements.procedures.monitor import Monitor
from thzdaq_core.domain.measurements.procedures.pv_curve import PVCurve, YFactorVoltage
from thzdaq_core.domain.measurements.procedures.reflection import SisReflection
from thzdaq_core.domain.measurements.procedures.shot_noise import ShotNoise
from thzdaq_core.domain.measurements.procedures.sis_tools import CLCurve, Demagnetize
from thzdaq_core.domain.measurements.procedures.two_sb import (
    IfBalance,
    PumpBalance,
    SidebandRatio,
    TwoSbNoise,
    TwoSbOptimization,
)

BUILTIN = (
    CLCurve,
    Demagnetize,
    GridCurrentAngle,
    IFNoise,
    IVCurve,
    IfBalance,
    Monitor,
    PVCurve,
    PumpBalance,
    ShotNoise,
    SidebandRatio,
    SisReflection,
    TwoSbNoise,
    TwoSbOptimization,
    YFactorVoltage,
)
