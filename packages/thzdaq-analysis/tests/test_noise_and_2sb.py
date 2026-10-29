import pytest
from thzdaq_analysis.noise import match_hot_cold
from thzdaq_analysis.shot_noise import dynamic_resistance, linear_fit
from thzdaq_analysis.two_sb import sideband_rejection


def test_match_hot_cold_pairs_nearest_voltage():
    hot = [(1.0, -30), (2.0, -29), (3.0, -28)]
    cold = [(1.1, -32), (1.9, -31), (3.05, -30)]
    assert match_hot_cold(hot, cold, window=2) == [
        (1.0, -30, -32),
        (2.0, -29, -31),
        (3.0, -28, -30),
    ]


def test_linear_fit_and_resistance():
    assert linear_fit([0, 1, 2], [1, 3, 5]) == pytest.approx((2, 1))
    assert dynamic_resistance([0, 1e-3], [0, 50e-6]) == pytest.approx(20)
    with pytest.raises(ValueError):
        linear_fit([1, 1], [1, 2])


def test_srr_of_ideal_mixer_matches_tone_ratio():
    # Equal channel gains: SRR equals the tone ratio
    upper, lower = sideband_rejection(-30, -32, -30, -32, -20, -40, -40, -20)
    assert upper == pytest.approx(20) and lower == pytest.approx(20)
