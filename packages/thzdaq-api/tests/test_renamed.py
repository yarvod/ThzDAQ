"""Procedures renamed: files, commands and grants with the names they had before."""

import json

import msgspec
from thzdaq_api.measurement_file import (
    PLOTS,
    Measurement,
    read_measurement,
    write_measurement,
)
from thzdaq_api.measurements import PlotInfo, ProcedureSummary, saved_plots
from thzdaq_api.procedures import (
    CURRENT_VS_GRID_ANGLE,
    CURRENT_VS_VOLTAGE,
    NOISE_TEMPERATURE_VS_FREQUENCY,
    RENAMED,
    current_name,
    former_names,
)
from thzdaq_api.scripts import Grant

IV = PlotInfo("iv", "I-V", "iv", "voltage", "current")
ADDED = PlotInfo("scan", "Scan", "scan", "voltage", "power")
CATALOG = (ProcedureSummary(CURRENT_VS_VOLTAGE, "SIS I-V curve", "", (IV,)),)


def test_old_names_lead_to_the_current_ones():
    assert current_name("sis.iv_curve") == CURRENT_VS_VOLTAGE
    assert current_name("if.hot_cold") == NOISE_TEMPERATURE_VS_FREQUENCY
    assert current_name(CURRENT_VS_VOLTAGE) == CURRENT_VS_VOLTAGE
    assert current_name("custom.scan") == "custom.scan"
    assert former_names(CURRENT_VS_VOLTAGE) == ["sis.iv_curve"]
    # The grid's measurement left a group of its own for SIS
    assert former_names(CURRENT_VS_GRID_ANGLE) == [
        "grid.current_angle",
        "grid.current_vs_angle",
    ]
    # No name is both old and current: an old one never leads to another old one
    assert not set(RENAMED) & set(RENAMED.values())


def test_a_file_of_an_old_name_draws_the_plots_of_its_procedure_now(tmp_path):
    old = Measurement("sis.iv_curve", "SIS I-V curve", 3)
    old.metadata[PLOTS] = [msgspec.to_builtins(ADDED)]  # a script's m.plot then
    data = old.to_dict()
    del data["plots"]  # written before files kept their plots
    path = tmp_path / "000003_sis_iv_curve.json"
    path.write_text(json.dumps(data))
    found = read_measurement(path)
    assert found.plots is None
    assert saved_plots(found, CATALOG) == (IV, ADDED)


def test_a_file_keeps_its_plots_however_the_procedure_changes(tmp_path):
    kept = PlotInfo("p", "P-V", "pv", "voltage", "power")
    measurement = Measurement("sis.gone", plots=[msgspec.to_builtins(kept)])
    found = read_measurement(write_measurement(measurement, tmp_path / "m.json"))
    assert saved_plots(found, CATALOG) == (kept,)
    # Kept empty is drawn with none, not with those of the procedure
    measurement = Measurement(CURRENT_VS_VOLTAGE, plots=[])
    found = read_measurement(write_measurement(measurement, tmp_path / "e.json"))
    assert saved_plots(found, CATALOG) == ()


def test_a_grant_to_run_names_the_procedure_as_it_is_now():
    assert Grant.parse("run:sis.iv_curve") == Grant("run", CURRENT_VS_VOLTAGE)
    assert Grant.parse("set:sis_bias_1") == Grant("set", "sis_bias_1")
