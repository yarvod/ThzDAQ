"""Limits and the safe state through LocalLab, as a client sees them."""

import copy

import pytest
from thzdaq_api.devices import (
    DescribeDevice,
    ReadDevice,
    SafeState,
    SafeValue,
    SetQuantity,
)
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.leases import EXCLUSIVE
from thzdaq_api.station import GetStation, UpdateStation

SAFETY = {
    "limits": {
        "sis_bias_1": {
            "voltage_set": {"min": -5e-3, "max": 5e-3, "warn_max": 4e-3, "step": 1e-3}
        },
    },
    "safe_state": {
        "sis_bias_1": {"voltage_set": 0},
        "signal_generator_1": {"output": False},
    },
}


@pytest.fixture
def guarded(lab):
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    profile["safety"] = SAFETY
    lab.call(UpdateStation(profile=profile))
    return lab


def quantities(lab, ref):
    return {q.key: q for q in lab.call(DescribeDevice(ref=ref)).quantities}


def test_a_device_describes_its_limits(guarded):
    bias = quantities(guarded, "sis_bias_1")
    voltage = bias["voltage_set"]
    assert (voltage.minimum, voltage.maximum) == (-5e-3, 5e-3)
    assert (voltage.warn_maximum, voltage.step, voltage.rate) == (4e-3, 1e-3, None)
    assert bias["active"].danger and not voltage.danger
    # The passport of the real driver, also on a simulated bench
    assert quantities(guarded, "power_supply_1:3")["voltage_set"].maximum == 5.0
    assert quantities(guarded, "signal_generator_1")["power_level"].maximum == 25.0


def test_a_value_beyond_the_limits_is_refused_and_nothing_changes(guarded):
    guarded.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="2 mV"))
    with pytest.raises(LabError) as caught:
        guarded.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="6 mV"))
    assert caught.value.code == ErrorCode.OUT_OF_LIMITS
    assert "above 0.005 V (bench)" in caught.value.message
    reading = guarded.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",)))
    assert reading.values["voltage_set"] == pytest.approx(2e-3)


def test_the_safe_state_goes_on_past_a_device_that_refuses(guarded):
    guarded.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="3 mV"))
    guarded.call(SetQuantity(ref="signal_generator_1", key="output", value=True))
    leases = guarded.assembled.runs.leases
    leases.acquire(7, "a sweep", {"sis_bias_1": EXCLUSIVE}, share=False)
    report = guarded.call(SafeState())
    assert [(v.ref, v.key) for v in report] == [
        ("sis_bias_1", "voltage_set"),
        ("signal_generator_1", "output"),
    ]
    assert "sweep" in report[0].error
    assert report[1] == SafeValue("signal_generator_1", "output", False)
    assert guarded.call(SafeState(share=True))[0] == SafeValue(
        "sis_bias_1", "voltage_set", 0.0
    )
    reading = guarded.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",)))
    assert reading.values["voltage_set"] == 0.0
