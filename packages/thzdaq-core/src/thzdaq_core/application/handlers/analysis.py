"""Operations of analysis: the contract is in SI units, thzdaq_analysis in the
units of the plots (mV, µA); its defaults stay its own."""

import math
from typing import Any, Dict, Optional, Sequence, Tuple

from thzdaq_analysis.iv import (
    IVAnalysisConfig,
    IVAnalysisParameters,
    IVGapConfig,
    IVResistanceAnalysis,
    NumpyIVAnalyzerFactory,
)
from thzdaq_api import analysis as api
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_instruments.units import MV, UA

from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.runs import Runs

SLOPE = UA / MV  # µA/mV -> A/V

# Option -> (part of the analysis parameters, its field, its unit in SI; None: a count)
IV_OPTIONS: Dict[str, Tuple[str, str, Optional[float]]] = {
    "rn_from": ("resistance", "rn_min_voltage_mv", MV),
    "rn_to": ("resistance", "rn_max_voltage_mv", MV),
    "rj_from": ("resistance", "rj_min_voltage_mv", MV),
    "rj_to": ("resistance", "rj_max_voltage_mv", MV),
    "gap_from": ("gap", "gap_min_voltage_mv", MV),
    "gap_to": ("gap", "gap_max_voltage_mv", MV),
    "gap_slope_factor": ("gap", "gap_slope_factor", None),
    "smoothing_window": ("gap", "smoothing_window", None),
    "smoothing_degree": ("gap", "smoothing_degree", None),
    "interpolation_points": ("gap", "interpolation_points", None),
}


def iv_parameters(options: api.IVOptions) -> IVAnalysisParameters:
    """The options that are set, over the analysis defaults; ValueError if wrong."""
    given: Dict[str, Dict[str, Any]] = {"resistance": {}, "gap": {}}
    for option, (part, field, unit) in IV_OPTIONS.items():
        value = getattr(options, option)
        if value is not None:
            given[part][field] = value if unit is None else value / unit
    return IVAnalysisParameters(
        resistance=IVAnalysisConfig(**given["resistance"]),
        gap=IVGapConfig(**given["gap"]),
    )


def iv_analysis(result: IVResistanceAnalysis) -> api.IVAnalysis:
    fit, tangent, gap = result.rn_fit, result.rj_tangent, result.gap
    return api.IVAnalysis(
        rn=api.IVLine(
            resistance=fit.resistance_ohm,
            slope=fit.slope_ua_per_mv * SLOPE,
            intercept=fit.intercept_ua * UA,
            voltage_range=tuple(v * MV for v in fit.line_voltage_range_mv),
            point=(fit.reference_voltage_mv * MV, fit.reference_current_ua * UA),
        ),
        rj=api.IVLine(
            resistance=tangent.resistance_ohm,
            slope=tangent.slope_ua_per_mv * SLOPE,
            intercept=0.0,
            voltage_range=tuple(v * MV for v in tangent.line_voltage_range_mv),
            point=(tangent.touch_voltage_mv * MV, tangent.touch_current_ua * UA),
        ),
        q=result.q,
        r_squared=fit.r_squared,
        gap=None
        if gap is None
        else api.IVGap(
            voltage=gap.voltage_mv * MV,
            current_step=gap.current_step_ua * UA,
            lower=(gap.lower_voltage_mv * MV, gap.lower_current_ua * UA),
            upper=(gap.upper_voltage_mv * MV, gap.upper_current_ua * UA),
        ),
    )


def analyzed(
    voltage: Sequence[float], current: Sequence[float], options: api.IVOptions
) -> api.IVAnalysis:
    """An I-V curve in SI (a point not finite is left out); LabError
    INVALID_ARGUMENTS says what the analysis could not take."""
    try:
        analyzer = NumpyIVAnalyzerFactory().create(iv_parameters(options))
        result = analyzer.analyze([v / MV for v in voltage], [i / UA for i in current])
    except ValueError as e:
        raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
    return iv_analysis(result)


def number(value: Any) -> float:
    """A recorded value as the analysis takes it: not a number (a missing or
    a text value) as NaN, which it leaves out."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return math.nan


class AnalyzeIv(Handler[api.AnalyzeIv, api.IVAnalysis]):
    operation = api.AnalyzeIv

    def handle(self, args, origin):
        return analyzed(args.voltage, args.current, args.options)


class AnalyzeMeasurementIv(Handler[api.AnalyzeMeasurementIv, api.MeasurementIv]):
    """The curve by its plot: the one the measurement draws for this analysis
    in the table asked for (any table when none is), else the usual keys."""

    operation = api.AnalyzeMeasurementIv

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        found = self.runs.published(args.id)
        plot = next(
            (
                p
                for p in found.plots
                if p.analysis == api.IV and args.table in (None, p.table)
            ),
            None,
        )
        table, records = found.table(args.table or (plot.table if plot else None))
        keys = (
            args.voltage or (plot.x if plot else api.VOLTAGE),
            args.current or (plot.y if plot else api.CURRENT),
        )
        voltage, current = (
            [number(v) for v in table.data[column.key][:records]]
            for column in found.columns(table, keys)
        )
        points = sum(
            math.isfinite(v) and math.isfinite(i) for v, i in zip(voltage, current)
        )
        return api.MeasurementIv(
            id=found.run.id,
            table=table.name,
            voltage=keys[0],
            current=keys[1],
            points=points,
            analysis=analyzed(voltage, current, args.options),
        )
