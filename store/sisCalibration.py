import ast
import math
import operator
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
            "5.4767381740816745e-09 / 5",
            "-0.04757314547896385 / 5",
        ],
        "CurrentDAC": [-1322560, 32801.19921875],
        "CurrentLimits": [-0.0020000000949949026, 0.0020000000949949026],
        "CurrentMonitorResistance": 20,
        "CurrentStep": 9.999999974752427e-07,
        "VoltageAdc": [
            "0.24375 * 6.53895619339726e-09",
            "-0.056775 * 0.24375",
        ],
        "VoltageDac": [-1322980, 32810.3984375],
        "VoltageLimits": [-0.019999999552965164, 0.019999999552965164],
        "VoltageStep": 9.999999747378752e-06,
    },
}

EXPRESSION_MAX_LENGTH = 200
EXPRESSION_MAX_NODES = 50
EXPRESSION_MAX_POWER = 100

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _normalize_number(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            f"'{field_name}' must contain only numbers or arithmetic expressions"
        )
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise ValueError(f"'{field_name}' must contain only finite numbers")
    return value if isinstance(value, int) else float(value)


def evaluate_numeric_expression(expression: str, field_name: str = "value"):
    expression = expression.strip()
    if not expression:
        raise ValueError(f"'{field_name}' contains an empty expression")
    if len(expression) > EXPRESSION_MAX_LENGTH:
        raise ValueError(f"'{field_name}' expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise ValueError(
            f"Invalid expression in '{field_name}': {expression}"
        ) from error
    if sum(1 for _ in ast.walk(tree)) > EXPRESSION_MAX_NODES:
        raise ValueError(f"'{field_name}' expression is too complex")

    def evaluate_node(node):
        if isinstance(node, ast.Expression):
            return evaluate_node(node.body)
        if isinstance(node, ast.Constant):
            return _normalize_number(node.value, field_name)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _normalize_number(
                _UNARY_OPERATORS[type(node.op)](evaluate_node(node.operand)),
                field_name,
            )
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = evaluate_node(node.left)
            right = evaluate_node(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > EXPRESSION_MAX_POWER:
                raise ValueError(
                    f"Power in '{field_name}' must be between "
                    f"-{EXPRESSION_MAX_POWER} and {EXPRESSION_MAX_POWER}"
                )
            try:
                result = _BINARY_OPERATORS[type(node.op)](left, right)
            except (ArithmeticError, OverflowError) as error:
                raise ValueError(
                    f"Unable to calculate expression in '{field_name}': {expression}"
                ) from error
            return _normalize_number(result, field_name)
        raise ValueError(
            f"Unsupported expression in '{field_name}'. Use only numbers, "
            "+, -, *, /, ** and parentheses"
        )

    return evaluate_node(tree)


def _normalize_coefficient(value, field_name: str, preserve_expression: bool):
    if isinstance(value, str):
        evaluated = evaluate_numeric_expression(value, field_name)
        return value.strip() if preserve_expression else evaluated
    return _normalize_number(value, field_name)


def _normalize_sis_calibration(
    calibration: Mapping, preserve_expressions: bool
) -> dict:
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
            normalized[field_name] = _normalize_coefficient(
                value, field_name, preserve_expressions
            )
            continue
        if not isinstance(value, (list, tuple)) or len(value) != vector_length:
            raise ValueError(
                f"'{field_name}' must be an array of {vector_length} coefficients"
            )
        normalized[field_name] = [
            _normalize_coefficient(item, field_name, preserve_expressions)
            for item in value
        ]
    return normalized


def normalize_sis_calibration(calibration: Mapping) -> dict:
    return _normalize_sis_calibration(calibration, preserve_expressions=True)


def evaluate_sis_calibration(calibration: Mapping) -> dict:
    return _normalize_sis_calibration(calibration, preserve_expressions=False)


def default_sis_calibration(bias_dev: str) -> dict:
    calibration = DEFAULT_SIS_CALIBRATIONS.get(
        bias_dev, DEFAULT_SIS_CALIBRATIONS["DEV4"]
    )
    return deepcopy(calibration)
