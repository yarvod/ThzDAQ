import re

import msgspec
import pytest
from thzdaq_api import catalog, wire
from thzdaq_api.devices import SetQuantity
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.operation import Rights


@pytest.mark.parametrize("op", catalog.OPERATIONS, ids=lambda op: op.name)
def test_every_operation_is_described(op):
    assert re.fullmatch(r"[a-z][a-z_]*", op.name)  # usable as an MCP tool name
    assert op.__doc__ and len(op.__doc__.split()) >= 5
    assert isinstance(op.rights, Rights)
    description = catalog.schema(op)["$defs"][op.__name__]["description"]
    assert description.split() == op.__doc__.split()  # what a model reads
    msgspec.json.schema(op.result_type())  # the result can travel too


def test_names_are_unique_and_found():
    assert len(catalog.BY_NAME) == len(catalog.OPERATIONS)
    assert catalog.operation("set_quantity") is SetQuantity
    with pytest.raises(LabError) as caught:
        catalog.operation("set_quantities")
    assert caught.value.code == ErrorCode.UNKNOWN_OPERATION


def test_arguments_travel_and_are_checked():
    op = SetQuantity(ref="sis_bias_1", key="voltage_set", value="2.3mV")
    assert wire.decode_arguments(op.name, wire.encode(op)) == op
    with pytest.raises(LabError) as caught:
        wire.decode_arguments("set_quantity", b'{"ref": "sis_bias_1", "key": 1}')
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    with pytest.raises(LabError):  # a misspelt argument is not ignored
        wire.decode_arguments("read_device", b'{"ref": "a", "kyes": ["x"]}')


def test_failures_travel():
    error = LabError(ErrorCode.NOT_FOUND, "no device 'x'", "see list_devices")
    again = wire.decode_failure(wire.encode(error.failure()))
    assert (again.code, again.message, again.hint) == (
        ErrorCode.NOT_FOUND,
        "no device 'x'",
        "see list_devices",
    )


def test_measurement_values_travel_with_complex_and_nan():
    import math

    from thzdaq_api.data import decode_values, encode_values

    record = {"s11": complex(0.1, -0.2), "tn": math.nan, "f": [1.0, math.inf]}
    again = decode_values(msgspec.json.decode(wire.encode(encode_values(record))))
    assert again["s11"] == complex(0.1, -0.2) and math.isnan(again["tn"])
    assert again["f"] == [1.0, math.inf]
