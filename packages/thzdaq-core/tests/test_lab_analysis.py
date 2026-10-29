"""Analysis as operations: the daemon computes, in SI units, for every client."""

import pytest
from thzdaq_api.analysis import AnalyzeIv, IVOptions
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_instruments.sim import SimSisBlock


def simulated_iv():
    block = SimSisBlock()
    voltage = tuple(i * 7e-3 / 350 for i in range(351))
    return voltage, tuple(block.iv_current(v) for v in voltage), block


def test_an_iv_curve_gives_rn_rj_and_the_gap_in_si(lab):
    voltage, current, block = simulated_iv()
    result = lab.call(AnalyzeIv(voltage=voltage, current=current))
    above_gap = 1 / (1 / block.normal_resistance + 1 / block.subgap_resistance)
    assert result.rn.resistance == pytest.approx(above_gap, rel=0.02)
    assert result.rn.slope == pytest.approx(1 / result.rn.resistance, rel=1e-6)
    assert result.rj.resistance > result.rn.resistance and result.q > 1
    assert result.gap.voltage == pytest.approx(block.gap_voltage, abs=0.1e-3)
    low, high = result.rn.voltage_range
    assert 0 < low < high <= voltage[-1]  # volts, where to draw the fit


def test_options_narrow_the_search_in_volts(lab):
    voltage, current, _ = simulated_iv()
    result = lab.call(
        AnalyzeIv(
            voltage=voltage,
            current=current,
            options=IVOptions(rn_from=5e-3, smoothing_window=11),
        )
    )
    assert result.rn.voltage_range[0] >= 5e-3 - 1e-9


@pytest.mark.parametrize(
    "operation",
    [
        AnalyzeIv(voltage=(0.0, 1e-3), current=(0.0,)),
        AnalyzeIv(
            voltage=(0.0, 1e-3), current=(0.0, 1e-6), options=IVOptions(rj_to=-1e-3)
        ),
        AnalyzeIv(
            voltage=(0.0, 1e-3),
            current=(0.0, 1e-6),
            options=IVOptions(smoothing_window=4),
        ),
    ],
)
def test_wrong_curves_and_options_are_named(lab, operation):
    with pytest.raises(LabError) as caught:
        lab.call(operation)
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
