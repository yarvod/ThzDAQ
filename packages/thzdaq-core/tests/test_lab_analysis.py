"""Analysis as operations: the daemon computes, in SI units, for every client."""

import pytest
from thzdaq_api import present
from thzdaq_api.analysis import AnalyzeIv, AnalyzeMeasurementIv, IVOptions
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurement_file import read_measurement
from thzdaq_api.measurements import StartMeasurement, WaitMeasurement
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE
from thzdaq_api.sessions import EndSession, RecordSession, StartSession
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


def test_a_measurements_iv_curve_is_analysed_on_every_record(lab):
    run = lab.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            devices={"bias": "sis_bias_1"},
            typed={"voltage": "0:7:71", "settle_time": "0", "first_point_delay": "0"},
        )
    )
    info = lab.call(WaitMeasurement(id=run.id, timeout=10))
    saved = read_measurement(info.path)
    # Its table and columns are those of the plot it offers the analysis on
    found = lab.call(AnalyzeMeasurementIv(id=run.id))
    assert (found.table, found.voltage, found.current, found.points) == (
        "iv",
        "voltage",
        "current",
        71,
    )
    assert found.analysis == lab.call(
        AnalyzeIv(
            voltage=tuple(saved.column("iv", "voltage")),
            current=tuple(saved.column("iv", "current")),
        )
    )
    told = present.iv(found)
    assert "table iv (voltage, current; 71 points)" in told
    assert f"Rn = {found.analysis.rn.resistance:.4g} Ω" in told
    assert f"gap {found.analysis.gap.voltage * 1e3:.4g} mV" in told
    narrowed = lab.call(
        AnalyzeMeasurementIv(id=run.id, options=IVOptions(rn_from=5e-3))
    )
    assert narrowed.analysis.rn.voltage_range[0] >= 5e-3 - 1e-9


def test_a_curve_without_its_plot_is_found_by_its_table_and_the_usual_keys(lab):
    voltage, current, _ = simulated_iv()
    run = lab.call(StartSession(title="iv by hand"))
    rows = tuple({"voltage": v, "current": i} for v, i in zip(voltage, current))
    lab.call(RecordSession(id=run.id, table="sweep", rows=rows))
    lab.call(RecordSession(id=run.id, table="notes", rows=({"text": "pumped"},)))
    with pytest.raises(LabError) as caught:  # which of its two tables?
        lab.call(AnalyzeMeasurementIv(id=run.id))
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    assert caught.value.hint == "tables: sweep (351 records), notes (1 records)"
    found = lab.call(AnalyzeMeasurementIv(id=run.id, table="sweep"))
    assert found.points == 351
    assert found.analysis == lab.call(AnalyzeIv(voltage=voltage, current=current))
    with pytest.raises(LabError) as caught:
        lab.call(AnalyzeMeasurementIv(id=run.id, table="sweep", current="i"))
    assert caught.value.code == ErrorCode.NOT_FOUND
    lab.call(EndSession(id=run.id))


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
