from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

import numpy as np


@dataclass(frozen=True)
class IVAnalysisConfig:
    rn_min_voltage_mv: float = 4.0
    rn_max_voltage_mv: Optional[float] = None
    rj_min_voltage_mv: float = 0.0
    rj_max_voltage_mv: float = 2.8


@dataclass(frozen=True)
class LinearFit:
    resistance_ohm: float
    slope_ua_per_mv: float
    intercept_ua: float
    r_squared: float
    reference_voltage_mv: float
    reference_current_ua: float
    point_count: int
    line_voltage_range_mv: tuple[float, float]

    def current_ua(self, voltage_mv):
        return self.slope_ua_per_mv * voltage_mv + self.intercept_ua


@dataclass(frozen=True)
class SupportingTangent:
    resistance_ohm: float
    slope_ua_per_mv: float
    touch_voltage_mv: float
    touch_current_ua: float
    minimum_clearance_ua: float
    point_count: int
    line_voltage_range_mv: tuple[float, float]

    def current_ua(self, voltage_mv):
        return self.slope_ua_per_mv * voltage_mv


@dataclass(frozen=True)
class IVResistanceAnalysis:
    rn_fit: LinearFit
    rj_tangent: SupportingTangent
    q: float

    @property
    def rn_ohm(self) -> float:
        return self.rn_fit.resistance_ohm

    @property
    def rj_ohm(self) -> float:
        return self.rj_tangent.resistance_ohm


class IVAnalyzer(Protocol):
    def analyze(
        self,
        voltage_mv: Sequence[float],
        current_ua: Sequence[float],
    ) -> IVResistanceAnalysis:
        ...


class NumpyIVResistanceAnalyzer:
    """Calculate Rn, the lower supporting-tangent Rj, and Q for one I-V curve.

    Input voltage is in mV and current is in µA. The analyzer has no Qt or
    plotting dependencies, so its range policy can be replaced through config
    or the whole implementation can be injected through ``IVAnalyzer``.
    """

    def __init__(self, config: Optional[IVAnalysisConfig] = None):
        self.config = config or IVAnalysisConfig()
        self._validate_config()

    def analyze(
        self,
        voltage_mv: Sequence[float],
        current_ua: Sequence[float],
    ) -> IVResistanceAnalysis:
        voltage = np.asarray(voltage_mv, dtype=float)
        current = np.asarray(current_ua, dtype=float)
        if voltage.ndim != 1 or current.ndim != 1:
            raise ValueError("Voltage and current must be one-dimensional arrays")
        if voltage.shape != current.shape:
            raise ValueError("Voltage and current arrays must have the same shape")

        finite = np.isfinite(voltage) & np.isfinite(current)
        if np.count_nonzero(finite) < 2:
            raise ValueError("The I-V curve must contain at least two finite points")

        rn_fit = self._calculate_rn(voltage, current, finite)
        rj_tangent = self._calculate_rj(voltage, current, finite)
        return IVResistanceAnalysis(
            rn_fit=rn_fit,
            rj_tangent=rj_tangent,
            q=rj_tangent.resistance_ohm / rn_fit.resistance_ohm,
        )

    def _calculate_rn(self, voltage, current, finite) -> LinearFit:
        config = self.config
        rn_mask = finite & (voltage >= config.rn_min_voltage_mv)
        if config.rn_max_voltage_mv is not None:
            rn_mask &= voltage <= config.rn_max_voltage_mv
        if np.count_nonzero(rn_mask) < 2:
            raise ValueError("Not enough points in the Rn fit range")

        rn_voltage = voltage[rn_mask]
        rn_current = current[rn_mask]
        if np.unique(rn_voltage).size < 2:
            raise ValueError("The Rn fit requires at least two different voltages")

        slope, intercept = np.polyfit(rn_voltage, rn_current, 1)
        slope = float(slope)
        intercept = float(intercept)
        if slope <= 0 or np.isclose(slope, 0):
            raise ValueError("The Rn fit must have a positive non-zero slope")

        model_current = slope * rn_voltage + intercept
        residual_sum = float(np.sum((rn_current - model_current) ** 2))
        total_sum = float(np.sum((rn_current - np.mean(rn_current)) ** 2))
        r_squared = 1.0 - residual_sum / total_sum if total_sum > 0 else np.nan
        reference_index = int(np.argmin(np.abs(rn_current - model_current)))
        line_max_voltage = (
            float(np.max(rn_voltage))
            if config.rn_max_voltage_mv is None
            else config.rn_max_voltage_mv
        )

        return LinearFit(
            resistance_ohm=1000.0 / slope,
            slope_ua_per_mv=slope,
            intercept_ua=intercept,
            r_squared=float(r_squared),
            reference_voltage_mv=float(rn_voltage[reference_index]),
            reference_current_ua=float(rn_current[reference_index]),
            point_count=int(np.count_nonzero(rn_mask)),
            line_voltage_range_mv=(config.rn_min_voltage_mv, line_max_voltage),
        )

    def _calculate_rj(self, voltage, current, finite) -> SupportingTangent:
        config = self.config
        rj_mask = (
            finite
            & (voltage > max(0.0, config.rj_min_voltage_mv))
            & (voltage <= config.rj_max_voltage_mv)
            & (current > 0.0)
        )
        if np.count_nonzero(rj_mask) < 2:
            raise ValueError("Not enough positive points in the Rj tangent range")

        indices = np.flatnonzero(rj_mask)
        indices = indices[np.argsort(voltage[indices], kind="stable")]
        slopes = current[indices] / voltage[indices]
        minimum_slope = float(np.min(slopes))
        equal_minimum = np.isclose(
            slopes,
            minimum_slope,
            rtol=1e-12,
            atol=1e-12,
        )
        touch_index = int(indices[np.flatnonzero(equal_minimum)[0]])
        touch_voltage = float(voltage[touch_index])
        touch_current = float(current[touch_index])
        slope = touch_current / touch_voltage

        clearance = current[indices] - slope * voltage[indices]
        minimum_clearance = float(np.min(clearance))
        clearance_tolerance = 1e-10 * max(
            1.0,
            float(np.max(np.abs(current[indices]))),
        )
        if minimum_clearance < -clearance_tolerance:
            raise RuntimeError("The calculated Rj tangent crosses the I-V curve")

        return SupportingTangent(
            resistance_ohm=1000.0 / slope,
            slope_ua_per_mv=slope,
            touch_voltage_mv=touch_voltage,
            touch_current_ua=touch_current,
            minimum_clearance_ua=minimum_clearance,
            point_count=len(indices),
            line_voltage_range_mv=(0.0, config.rj_max_voltage_mv),
        )

    def _validate_config(self):
        config = self.config
        if (
            config.rn_max_voltage_mv is not None
            and config.rn_max_voltage_mv <= config.rn_min_voltage_mv
        ):
            raise ValueError("Rn maximum voltage must be greater than its minimum")
        if config.rj_max_voltage_mv <= max(0.0, config.rj_min_voltage_mv):
            raise ValueError(
                "Rj maximum voltage must be positive and greater than its minimum"
            )
