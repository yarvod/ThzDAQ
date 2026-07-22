import math
from copy import deepcopy
from numbers import Real
from typing import Mapping


CALIBRATION_FIELDS = {
    "CurrentADC": 2,
    "CurrentDAC": 2,
    "CurrentLimits": 2,
    "CurrentMonitorResistance": None,
    "CurrentStep": None,
    "VoltageAdc": 2,
    "VoltageDac": 2,
    "VoltageLimits": 2,
    "VoltageStep": None,
}

DEFAULT_SIS_CALIBRATIONS = {
    "DEV2": {
        "CurrentADC": [2.7199096308549997e-09, -0.02362622693181038],
        "CurrentDAC": [-1382090, 32661.900390625],
        "CurrentLimits": [-0.0020000000949949026, 0.0020000000949949026],
        "CurrentMonitorResistance": 10,
        "CurrentStep": 9.999999974752427e-07,
        "VoltageAdc": [6.597875135128106e-09, -0.057308197021484375],
        "VoltageDac": [-1177910, 32684.30078125],
        "VoltageLimits": [-0.019999999552965164, 0.019999999552965164],
        "VoltageStep": 9.999999747378752e-06,
    },
    "DEV4": {
        "CurrentADC": [
            5.4767381740816745e-09 / 5,
            -0.04757314547896385 / 5,
        ],
        "CurrentDAC": [-1322560, 32801.19921875],
        "CurrentLimits": [-0.0020000000949949026, 0.0020000000949949026],
        "CurrentMonitorResistance": 20,
        "CurrentStep": 9.999999974752427e-07,
        "VoltageAdc": [
            0.24375 * 6.53895619339726e-09,
            -0.056775 * 0.24375,
        ],
        "VoltageDac": [-1322980, 32810.3984375],
        "VoltageLimits": [-0.019999999552965164, 0.019999999552965164],
        "VoltageStep": 9.999999747378752e-06,
    },
}


def _normalize_number(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"'{field_name}' must contain only numbers")
    if not math.isfinite(float(value)):
        raise ValueError(f"'{field_name}' must contain only finite numbers")
    return value if isinstance(value, int) else float(value)


def normalize_sis_calibration(calibration: Mapping) -> dict:
    if not isinstance(calibration, Mapping):
        raise ValueError("Calibration coefficients must be a JSON object")

    missing = [key for key in CALIBRATION_FIELDS if key not in calibration]
    extra = [key for key in calibration if key not in CALIBRATION_FIELDS]
    if missing:
        raise ValueError(f"Missing calibration fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"Unknown calibration fields: {', '.join(extra)}")

    normalized = {}
    for field_name, vector_length in CALIBRATION_FIELDS.items():
        value = calibration[field_name]
        if vector_length is None:
            normalized[field_name] = _normalize_number(value, field_name)
            continue
        if not isinstance(value, (list, tuple)) or len(value) != vector_length:
            raise ValueError(
                f"'{field_name}' must be an array of {vector_length} numbers"
            )
        normalized[field_name] = [_normalize_number(item, field_name) for item in value]
    return normalized


def default_sis_calibration(bias_dev: str) -> dict:
    calibration = DEFAULT_SIS_CALIBRATIONS.get(
        bias_dev, DEFAULT_SIS_CALIBRATIONS["DEV4"]
    )
    return deepcopy(calibration)
