from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

import numpy as np


@dataclass(frozen=True)
class IVAnalysisConfig:
    rn_min_voltage_mv: float = 4.0
    rn_max_voltage_mv: Optional[float] = None
    rj_min_voltage_mv: float = 0.0
    rj_max_voltage_mv: float = 2.8

    def __post_init__(self):
        if (
            self.rn_max_voltage_mv is not None
            and self.rn_max_voltage_mv <= self.rn_min_voltage_mv
        ):
            raise ValueError("Rn maximum voltage must be greater than its minimum")
        if self.rj_max_voltage_mv <= max(0.0, self.rj_min_voltage_mv):
            raise ValueError(
                "Rj maximum voltage must be positive and greater than its minimum"
            )


@dataclass(frozen=True)
class IVGapConfig:
    gap_min_voltage_mv: float = 2.2
    gap_max_voltage_mv: float = 3.0
    gap_slope_factor: float = 2.0
    smoothing_window: int = 31
    smoothing_degree: int = 3
    interpolation_points: int = 1001

    def __post_init__(self):
        if self.gap_max_voltage_mv <= max(0.0, self.gap_min_voltage_mv):
            raise ValueError(
                "Gap maximum voltage must be positive and greater than its minimum"
            )
        if self.gap_slope_factor <= 1.0:
            raise ValueError("Gap slope factor must be greater than one")
        if self.smoothing_window < 3 or self.smoothing_window % 2 == 0:
            raise ValueError("Smoothing window must be an odd integer of at least 3")
        if self.smoothing_degree < 1:
            raise ValueError("Smoothing degree must be positive")
        if self.smoothing_degree >= self.smoothing_window:
            raise ValueError("Smoothing degree must be smaller than its window")
        if self.interpolation_points < self.smoothing_window:
            raise ValueError(
                "Interpolation point count must not be smaller than smoothing window"
            )


@dataclass(frozen=True)
class IVAnalysisParameters:
    resistance: IVAnalysisConfig = field(default_factory=IVAnalysisConfig)
    gap: IVGapConfig = field(default_factory=IVGapConfig)


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
class GapFeatures:
    voltage_mv: float
    current_step_ua: float
    lower_voltage_mv: float
    lower_current_ua: float
    upper_voltage_mv: float
    upper_current_ua: float
    upper_method: str


@dataclass(frozen=True)
class IVResistanceAnalysis:
    rn_fit: LinearFit
    rj_tangent: SupportingTangent
    q: float
    gap: Optional[GapFeatures] = None

    @property
    def rn_ohm(self) -> float:
        return self.rn_fit.resistance_ohm

    @property
    def rj_ohm(self) -> float:
        return self.rj_tangent.resistance_ohm

    @property
    def vgap_mv(self) -> Optional[float]:
        return None if self.gap is None else self.gap.voltage_mv

    @property
    def igap_ua(self) -> Optional[float]:
        return None if self.gap is None else self.gap.current_step_ua


class IVAnalyzer(Protocol):
    def analyze(
        self,
        voltage_mv: Sequence[float],
        current_ua: Sequence[float],
    ) -> IVResistanceAnalysis:
        ...


class IVGapAnalyzer(Protocol):
    def analyze(
        self,
        voltage_mv: Sequence[float],
        current_ua: Sequence[float],
        rn_fit: LinearFit,
    ) -> Optional[GapFeatures]:
        ...


class IVAnalyzerFactory(Protocol):
    def create(self, parameters: IVAnalysisParameters) -> IVAnalyzer:
        ...


class NumpyIVResistanceAnalyzer:
    """Calculate Rn, the lower supporting-tangent Rj, and Q for one I-V curve.

    Input voltage is in mV and current is in µA. The analyzer has no Qt or
    plotting dependencies, so its range policy can be replaced through config
    or the whole implementation can be injected through ``IVAnalyzer``.
    """

    def __init__(
        self,
        config: Optional[IVAnalysisConfig] = None,
        gap_analyzer: Optional[IVGapAnalyzer] = None,
    ):
        self.config = config or IVAnalysisConfig()
        self.gap_analyzer = gap_analyzer or NumpyIVGapAnalyzer()

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
            gap=self.gap_analyzer.analyze(
                voltage[finite],
                current[finite],
                rn_fit,
            ),
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


class NumpyIVGapAnalyzer:
    """Extract gap features from an I-V curve independently of Qt and plotting."""

    def __init__(self, config: Optional[IVGapConfig] = None):
        self.config = config or IVGapConfig()

    def analyze(
        self,
        voltage_mv: Sequence[float],
        current_ua: Sequence[float],
        rn_fit: LinearFit,
    ) -> Optional[GapFeatures]:
        config = self.config
        voltage = np.asarray(voltage_mv, dtype=float)
        current = np.asarray(current_ua, dtype=float)
        if voltage.ndim != 1 or current.ndim != 1 or voltage.shape != current.shape:
            return None
        finite = np.isfinite(voltage) & np.isfinite(current)
        positive = finite & (voltage >= 0.0)
        source_voltage, source_current = self._sorted_unique_curve(
            voltage[positive],
            current[positive],
        )
        if (
            source_voltage.size < 4
            or source_voltage[0] > config.gap_min_voltage_mv
            or source_voltage[-1] < config.gap_max_voltage_mv
        ):
            return None

        dense_voltage = np.linspace(
            source_voltage[0],
            source_voltage[-1],
            config.interpolation_points,
        )
        dense_current = np.interp(dense_voltage, source_voltage, source_current)
        smooth_current = self._savitzky_golay(
            dense_current,
            config.smoothing_window,
            config.smoothing_degree,
        )
        conductance = np.gradient(smooth_current, dense_voltage)

        gap_indices = np.flatnonzero(
            (dense_voltage >= config.gap_min_voltage_mv)
            & (dense_voltage <= config.gap_max_voltage_mv)
            & np.isfinite(conductance)
        )
        if gap_indices.size < 3:
            return None

        peak_index = int(gap_indices[np.argmax(conductance[gap_indices])])
        target_conductance = config.gap_slope_factor * rn_fit.slope_ua_per_mv
        if conductance[peak_index] < target_conductance:
            return None

        lower_region = gap_indices[gap_indices <= peak_index]
        upper_region = gap_indices[gap_indices >= peak_index]
        if lower_region.size < 2 or upper_region.size < 2:
            return None

        lower_voltage = self._last_level_crossing(
            dense_voltage,
            conductance,
            lower_region,
            target_conductance,
        )
        if lower_voltage is None:
            lower_index = int(
                lower_region[
                    np.argmin(np.abs(conductance[lower_region] - target_conductance))
                ]
            )
            lower_voltage = float(dense_voltage[lower_index])
        lower_current = float(np.interp(lower_voltage, dense_voltage, smooth_current))

        normal_residual = smooth_current - rn_fit.current_ua(dense_voltage)
        upper_voltage = self._first_zero_crossing(
            dense_voltage,
            normal_residual,
            upper_region,
        )
        upper_method = "normal_fit_intersection"
        if upper_voltage is None:
            upper_voltage = self._first_level_crossing(
                dense_voltage,
                conductance,
                upper_region,
                target_conductance,
            )
            upper_method = "double_normal_slope"
        if upper_voltage is None:
            upper_index = int(
                upper_region[
                    np.argmin(np.abs(conductance[upper_region] - target_conductance))
                ]
            )
            upper_voltage = float(dense_voltage[upper_index])
            upper_method = "nearest_double_normal_slope"

        upper_current = float(np.interp(upper_voltage, dense_voltage, smooth_current))
        if upper_voltage <= lower_voltage or upper_current <= lower_current:
            return None

        center_current = lower_current + (upper_current - lower_current) / 2.0
        center_region = np.flatnonzero(
            (dense_voltage >= lower_voltage) & (dense_voltage <= upper_voltage)
        )
        center_voltage = self._first_level_crossing(
            dense_voltage,
            smooth_current,
            center_region,
            center_current,
        )
        if center_voltage is None:
            center_index = int(
                center_region[
                    np.argmin(np.abs(smooth_current[center_region] - center_current))
                ]
            )
            center_voltage = float(dense_voltage[center_index])

        return GapFeatures(
            voltage_mv=center_voltage,
            current_step_ua=upper_current - lower_current,
            lower_voltage_mv=lower_voltage,
            lower_current_ua=lower_current,
            upper_voltage_mv=upper_voltage,
            upper_current_ua=upper_current,
            upper_method=upper_method,
        )

    @staticmethod
    def _sorted_unique_curve(voltage, current):
        if voltage.size == 0:
            return voltage, current
        order = np.argsort(voltage, kind="stable")
        voltage = voltage[order]
        current = current[order]
        unique_voltage, inverse = np.unique(voltage, return_inverse=True)
        if unique_voltage.size == voltage.size:
            return voltage, current
        current_sum = np.zeros(unique_voltage.size, dtype=float)
        point_count = np.zeros(unique_voltage.size, dtype=int)
        np.add.at(current_sum, inverse, current)
        np.add.at(point_count, inverse, 1)
        return unique_voltage, current_sum / point_count

    @staticmethod
    def _savitzky_golay(values, requested_window: int, degree: int):
        point_count = len(values)
        window = min(requested_window, point_count)
        if window % 2 == 0:
            window -= 1
        minimum_window = degree + 1
        if minimum_window % 2 == 0:
            minimum_window += 1
        if window < minimum_window:
            return np.asarray(values, dtype=float)

        half_window = window // 2
        positions = np.arange(-half_window, half_window + 1, dtype=float)
        design = np.vander(positions, degree + 1, increasing=True)
        coefficients = np.linalg.pinv(design)[0]
        padded = np.pad(values, half_window, mode="reflect")
        return np.convolve(padded, coefficients[::-1], mode="valid")

    @classmethod
    def _first_zero_crossing(cls, x, values, indices) -> Optional[float]:
        return cls._first_level_crossing(x, values, indices, 0.0)

    @staticmethod
    def _level_crossings(x, values, indices, level: float) -> list[float]:
        crossings = []
        for left, right in zip(indices[:-1], indices[1:]):
            left_delta = values[left] - level
            right_delta = values[right] - level
            if left_delta == 0:
                crossings.append(float(x[left]))
                continue
            if left_delta * right_delta > 0:
                continue
            fraction = -left_delta / (right_delta - left_delta)
            crossings.append(float(x[left] + fraction * (x[right] - x[left])))
        if indices.size and values[indices[-1]] == level:
            crossings.append(float(x[indices[-1]]))
        return crossings

    @classmethod
    def _first_level_crossing(cls, x, values, indices, level) -> Optional[float]:
        crossings = cls._level_crossings(x, values, indices, level)
        return crossings[0] if crossings else None

    @classmethod
    def _last_level_crossing(cls, x, values, indices, level) -> Optional[float]:
        crossings = cls._level_crossings(x, values, indices, level)
        return crossings[-1] if crossings else None


class NumpyIVAnalyzerFactory:
    def create(self, parameters: IVAnalysisParameters) -> IVAnalyzer:
        return NumpyIVResistanceAnalyzer(
            config=parameters.resistance,
            gap_analyzer=NumpyIVGapAnalyzer(parameters.gap),
        )
