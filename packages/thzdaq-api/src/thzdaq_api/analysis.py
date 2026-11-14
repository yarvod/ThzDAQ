"""Analysis of measured data, done by the daemon so every client gets the same
result. Values are in SI units: volts, amperes, ohms."""

from typing import Optional, Tuple

import msgspec

from thzdaq_api.operation import Operation

Point = Tuple[float, float]  # (V, A)


class IVOptions(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Where the I-V analysis looks, in volts; an unset field keeps the
    analysis default (rn_to unset: up to the end of the curve)."""

    rn_from: Optional[float] = None  # Rn: a line fitted above this voltage
    rn_to: Optional[float] = None
    rj_from: Optional[float] = None  # Rj: the tangent from the origin below the gap
    rj_to: Optional[float] = None
    gap_from: Optional[float] = None  # where the current step is searched
    gap_to: Optional[float] = None
    gap_slope_factor: Optional[float] = None  # the step ends where the slope falls
    smoothing_window: Optional[int] = None  # odd number of points
    smoothing_degree: Optional[int] = None
    interpolation_points: Optional[int] = None


class IVLine(msgspec.Struct, frozen=True):
    """A straight line on the I-V curve: current = slope * voltage + intercept."""

    resistance: float  # ohm
    slope: float  # A/V
    intercept: float  # A
    voltage_range: Tuple[float, float]  # where to draw it
    point: Point  # the reference point of a fit, the touch point of a tangent


class IVGap(msgspec.Struct, frozen=True):
    voltage: float  # the middle of the current step
    current_step: float
    lower: Point
    upper: Point


class IVAnalysis(msgspec.Struct, frozen=True):
    rn: IVLine  # normal-state resistance: the fit above the gap
    rj: IVLine  # subgap resistance: the supporting tangent from the origin
    q: float  # Rj / Rn
    r_squared: float  # of the Rn fit
    gap: Optional[IVGap] = None  # None when no step is found


class AnalyzeIv(Operation[IVAnalysis]):
    """Analyze a SIS I-V curve: normal resistance Rn (a line fitted above the
    gap), subgap resistance Rj (the tangent from the origin), their ratio Q and
    the gap voltage and current step. Voltage in volts, current in amperes;
    options narrow where each value is searched."""

    voltage: Tuple[float, ...]
    current: Tuple[float, ...]
    options: IVOptions = IVOptions()
