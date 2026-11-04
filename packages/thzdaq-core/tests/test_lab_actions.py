"""Device actions through LocalLab: described, run in the lane, refused on a swept device."""

import pytest
from lab_helpers import bodies
from thzdaq_api.devices import CallAction, DescribeDevice, Trace
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ActionDone
from thzdaq_api.leases import EXCLUSIVE


def test_a_device_describes_its_actions(lab):
    actions = {a.key: a for a in lab.call(DescribeDevice(ref="chopper_1")).actions}
    assert list(actions) == ["to_hot", "to_cold", "start_rotation", "stop"]
    (frequency,) = actions["start_rotation"].arguments
    assert (frequency.unit, frequency.default, frequency.maximum) == ("Hz", 10.0, 20.0)
    assert lab.call(DescribeDevice(ref="power_supply_1:1")).actions == ()


def test_an_action_runs_and_is_told(lab):
    heard = []
    lab.subscribe(heard.append)
    chopper = lab.assembled.runs.bench.station.instrument("chopper_1")
    lab.call(CallAction(ref="chopper_1", action="to_hot"))
    assert chopper.position == "hot"
    done = lab.call(
        CallAction(
            ref="chopper_1", action="start_rotation", arguments={"frequency": "12 Hz"}
        )
    )
    assert done.result is None and chopper.running and chopper.frequency == 12.0
    told = bodies(heard, ActionDone)
    assert [(b.action, b.arguments, b.origin) for b in told] == [
        ("to_hot", {}, "test"),
        ("start_rotation", {"frequency": 12.0}, "test"),
    ]


def test_a_trace_comes_back(lab):
    ref = "spectrum_analyzer_1"
    lab.call(
        CallAction(
            ref=ref, action="configure", arguments={"center": "6 GHz", "span": "2 GHz"}
        )
    )
    trace = lab.call(CallAction(ref=ref, action="read_trace")).result
    assert isinstance(trace, Trace) and trace.imaginary is None
    assert min(trace.frequency) == pytest.approx(5e9)
    assert len(trace.frequency) == len(trace.values)


@pytest.mark.parametrize(
    "operation, code",
    [
        (CallAction(ref="chopper_1", action="spin"), ErrorCode.NOT_FOUND),
        (
            CallAction(
                ref="chopper_1", action="start_rotation", arguments={"frequency": 50}
            ),
            ErrorCode.INVALID_ARGUMENTS,
        ),
        (
            CallAction(ref="spectrum_analyzer_1", action="configure"),
            ErrorCode.INVALID_ARGUMENTS,
        ),
    ],
)
def test_failures_say_what_is_wrong(lab, operation, code):
    with pytest.raises(LabError) as caught:
        lab.call(operation)
    assert caught.value.code == code


def test_a_swept_device_takes_a_change_only_with_share_and_a_read_always(lab):
    leases = lab.assembled.runs.leases
    leases.acquire(7, "a sweep", {"spectrum_analyzer_1": EXCLUSIVE})
    configure = {"center": 6e9, "span": 1e9}
    with pytest.raises(LabError) as caught:
        lab.call(
            CallAction(
                ref="spectrum_analyzer_1", action="configure", arguments=configure
            )
        )
    assert caught.value.code == ErrorCode.CONFLICT
    lab.call(CallAction(ref="spectrum_analyzer_1", action="read_trace"))
    lab.call(
        CallAction(
            ref="spectrum_analyzer_1",
            action="configure",
            arguments=configure,
            share=True,
        )
    )


def test_a_sis_bias_writes_the_calibration_of_its_profile(lab):
    from thzdaq_core.domain.sis.calibration import (
        calibration_for,
        evaluate_sis_calibration,
    )

    actions = {a.key: a for a in lab.call(DescribeDevice(ref="sis_bias_1")).actions}
    assert actions["write_calibration"].danger  # it overwrites the block's memory
    station = lab.assembled.runs.bench.station
    instrument_id, spec = station.config.find_device("sis_bias_1")
    done = lab.call(CallAction(ref="sis_bias_1", action="write_calibration"))
    assert done.result == "OK"
    channel = station.instrument(instrument_id).channel(spec.channel)
    assert channel.calibration == evaluate_sis_calibration(
        calibration_for(spec.channel)
    )
    assert "write_calibration" not in {
        a.key for a in lab.call(DescribeDevice(ref="sis_coil_1")).actions
    }
