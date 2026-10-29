import pytest
from thzdaq_instruments.actions import Action, Argument, actions_of
from thzdaq_instruments.readings import ComplexTrace, Trace
from thzdaq_instruments.sim import (
    SimChopper,
    SimCompressor,
    SimNetworkAnalyzer,
    SimPowerSupply,
    SimSpectrumAnalyzer,
)


def by_key(target):
    return {action.key: action for action in actions_of(target)}


def test_from_capabilities_and_driver():
    assert list(by_key(SimChopper())) == ["to_hot", "to_cold", "start_rotation", "stop"]
    assert list(by_key(SimSpectrumAnalyzer())) == ["configure", "read_trace"]
    assert by_key(SimPowerSupply().channel(1)) == {}
    compressor = by_key(SimCompressor())
    assert compressor["turn_on"].danger and compressor["turn_off"].danger
    assert not by_key(SimChopper())["to_hot"].danger


def test_run_parses_arguments_with_units():
    chopper = SimChopper()
    actions = by_key(chopper)
    actions["start_rotation"].run(chopper, {"frequency": "12.5 Hz"})
    assert chopper.running and chopper.frequency == 12.5
    actions["stop"].run(chopper, {})
    assert not chopper.running
    actions["start_rotation"].run(chopper, {})  # the default frequency
    assert chopper.frequency == 10.0
    actions["to_hot"].run(chopper, {})
    assert chopper.position == "hot"


def test_reads_return_traces_and_change_nothing():
    spectrum, network = SimSpectrumAnalyzer(), SimNetworkAnalyzer()
    read = by_key(spectrum)["read_trace"]
    assert not read.changes and by_key(spectrum)["configure"].changes
    by_key(spectrum)["configure"].run(spectrum, {"center": "6 GHz", "span": 2e9})
    trace = read.run(spectrum, {})
    assert isinstance(trace, Trace) and min(trace.frequency) == pytest.approx(5e9)
    by_key(network)["configure"].run(
        network, {"start": 1e9, "stop": 2e9, "points": 11, "parameter": "S21"}
    )
    trace = by_key(network)["read_trace"].run(network, {})
    assert isinstance(trace, ComplexTrace) and len(trace.values) == 11


@pytest.mark.parametrize(
    "given, problem",
    [
        ({}, "frequency is required"),
        ({"frequency": 50}, "above"),
        ({"frequency": "fast"}, "not a number"),
        ({"frequency": 1, "speed": 2}, "unknown arguments"),
    ],
)
def test_wrong_arguments_are_named(given, problem):
    action = Action(
        "spin", "Spin", lambda t, frequency: None,
        arguments=(Argument("frequency", "Frequency", "Hz", maximum=20),),
    )  # fmt: skip
    with pytest.raises(ValueError, match=problem):
        action.bind(given)
