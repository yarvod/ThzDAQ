"""Operations of analysis: the contract is in SI units, thzdaq_analysis in the
units of the plots (mV, µA); its defaults stay its own."""

from typing import Any, Dict, Optional, Tuple

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


class AnalyzeIv(Handler[api.AnalyzeIv, api.IVAnalysis]):
    operation = api.AnalyzeIv

    def handle(self, args, origin):
        try:
            analyzer = NumpyIVAnalyzerFactory().create(iv_parameters(args.options))
            result = analyzer.analyze(
                [v / MV for v in args.voltage], [i / UA for i in args.current]
            )
        except ValueError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        return iv_analysis(result)
