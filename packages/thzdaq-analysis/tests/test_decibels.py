import pytest
from thzdaq_analysis.decibels import db_to_ratio, ratio_to_db


def test_db_roundtrip():
    assert db_to_ratio(3) == pytest.approx(1.995, rel=1e-3)
    assert ratio_to_db(db_to_ratio(2)) == pytest.approx(2)


def test_non_positive_ratio_rejected():
    with pytest.raises(ValueError):
        ratio_to_db(0)
