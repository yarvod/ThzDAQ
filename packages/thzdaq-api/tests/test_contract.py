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


def test_action_results_travel_as_values_or_traces():
    from thzdaq_api.devices import ActionResult, CallAction, Trace

    op = CallAction(
        ref="chopper_1", action="start_rotation", arguments={"frequency": "12 Hz"}
    )
    assert wire.decode_arguments(op.name, wire.encode(op)) == op
    assert (
        wire.decode_arguments(op.name, b'{"ref": "a", "action": "to_hot"}').arguments
        == {}
    )
    trace = Trace((1e9, 2e9), (0.1, 0.2), imaginary=(-0.1, 0.0), parameter="S21")
    for result in (None, 12.0, "OK", trace):
        done = ActionResult("a", "x", result)
        assert wire.decode_result(op, wire.encode(done)) == done


def test_iv_analysis_travels_with_its_options():
    from thzdaq_api.analysis import AnalyzeIv, IVOptions

    op = AnalyzeIv(
        voltage=(0.0, 1e-3), current=(0.0, 1e-6), options=IVOptions(rn_from=4e-3)
    )
    assert op.name == "analyze_iv"
    assert wire.decode_arguments(op.name, wire.encode(op)) == op
    with pytest.raises(LabError):  # a misspelt option is not ignored
        wire.decode_arguments(
            op.name, b'{"voltage": [], "current": [], "options": {"rn_form": 1}}'
        )


def test_safe_state_says_how_each_value_went():
    from thzdaq_api.devices import SafeState, SafeValue

    op = SafeState(share=True)
    assert op.name == "safe_state" and op.rights == Rights.SET
    report = (SafeValue("sis_bias_1", "voltage_set", 0.0), SafeValue("x", "y", 1, "no"))
    assert wire.decode_result(op, wire.encode(report)) == report
    assert ErrorCode("out_of_limits") is ErrorCode.OUT_OF_LIMITS


def test_a_slot_lists_the_devices_that_suit_it():
    from thzdaq_api.devices import DeviceInfo
    from thzdaq_api.measurements import SlotInfo

    def device(ref, kind, *capabilities):
        return DeviceInfo(
            ref, ref.upper(), "block", "sim.block", kind, kind, capabilities
        )

    sis = device("sis_bias_1", "sis_bias", "VoltageSource", "VoltageCurrentMeter")
    supply = device("ps:1", "channel", "VoltageSource", "VoltageCurrentMeter")
    meter = device("power_meter_1", "instrument", "PowerDetector")
    bias = SlotInfo("bias", "Bias", ("VoltageSource",), kind="sis_bias")
    assert bias.candidates([supply, sis, meter]) == [sis]  # the preferred kind
    assert bias.candidates([supply, meter]) == [supply]  # else any that suits
    anything = SlotInfo("power_meter_1", "Power meter", ())
    assert anything.candidates([sis, meter]) == [sis, meter]


def test_lists_are_typed_with_commas_semicolons_or_spaces():
    from thzdaq_api.measurements import split_list

    assert split_list(" 4, 6;8  10 ") == ["4", "6", "8", "10"]
    assert split_list("") == []


def test_a_reset_lane_fails_what_waits_and_starts_anew():
    import threading

    from thzdaq_api.lanes import LaneReset, Lanes

    lanes = Lanes()
    release, outcomes = threading.Event(), []
    lanes.submit(
        "nrx",
        lambda: release.wait(5) and "late",
        lambda r, e: outcomes.append(r),
        label="NRX",
    )
    lanes.submit("nrx", lambda: "never", lambda r, e: outcomes.append(e))
    while lanes.current != "NRX":
        threading.Event().wait(0.005)  # until the first job holds the lane
    assert lanes.reset("nrx") and not lanes.reset("sis")
    assert isinstance(outcomes[0], LaneReset)  # the waiting one failed at once
    assert lanes.call("nrx", lambda: "fresh") == "fresh"  # a new lane
    release.set()
    lanes.stop()
