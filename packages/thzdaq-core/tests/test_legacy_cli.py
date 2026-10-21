import subprocess
import sys
from pathlib import Path

import pytest
from thzdaq_core.station import Station, load_station
from thzdaq_core.station.cli import main
from thzdaq_core.station.legacy import slug, station_from_legacy

EXAMPLE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"

# Shape of [Configs] in the legacy settings.ini, as QSettings returns it
LEGACY = {
    "Prologix ethernet": [{"_name": "Prologix ethernet", "cid": 1, "host": "10.0.0.3", "port": "1234"}],
    "Agilent Signal Generator": [
        {"_name": "Agilent Signal Generator", "adapter": "PROLOGIX ETHERNET", "cid": 1, "gpib": 19, "host": "10.0.0.3", "port": "1234"},
        {"_name": "Agilent Signal Generator", "adapter": "PROLOGIX ETHERNET", "cid": 2, "gpib": 18, "host": "10.0.0.3", "port": "1234"},
    ],
    "Rigol Power Supply": [
        {"name": "IF switch", "adapter": "SOCKET", "cid": 1, "gpib": 1, "host": "10.0.0.14", "port": "5555"},
    ],
    "Scontel SIS Block": [
        {"adapter": "SOCKET", "bias_dev": "DEV4", "ctrl_dev": "DEV3", "cid": 1, "gpib": 0, "host": "10.0.0.83",
         "name": "Scontel SIS Block 1", "offset_current": 0.0, "offset_voltage": 4e-05, "port": "9876",
         "calibration_coefficients": {"VoltageStep": 1e-05}},
        {"adapter": "SOCKET", "bias_dev": "DEV2", "ctrl_dev": "DEV1", "cid": 2, "gpib": 0, "host": "10.0.0.83",
         "name": "Scontel SIS Block 2", "offset_current": -1.3e-06, "offset_voltage": -0.000187, "port": "9876"},
    ],
    "GRID": [{"_name": "GRID", "adapter": "HTTP", "cid": 1, "gpib": 0, "host": "10.0.0.52", "port": "80"}],
    "Sumitomo F70 Compressor": [{"_name": "Sumitomo F70 Compressor", "adapter": "HTTP", "cid": 1, "gpib": 0, "host": "10.0.0.106", "port": "21024"}],
    "Mystery Box": [{"adapter": "SOCKET", "host": "x", "port": "1"}],
}  # fmt: skip


class TestLegacyImport:
    def test_instruments_roles_and_notes(self):
        config, notes = station_from_legacy(LEGACY, name="lab")
        assert set(config.instruments) == {
            "signal_generator_1",
            "signal_generator_2",
            "power_supply_1",
            "sis_block_1",
            "grid_1",
            "compressor_1",
            "power_meter_1",
            "yig_filter_1",
            "chopper_1",
        }
        assert config.instruments["signal_generator_2"].connection.gpib == 18
        # The user's name is only the title, the id names the kind of device
        assert config.instruments["power_supply_1"].title == "IF switch"
        assert any("merged into sis_block_1" in note for note in notes)
        assert any("Mystery Box" in note for note in notes)
        assert any("Prologix ethernet" in note for note in notes)

    def test_sis_configs_become_roles_on_one_block(self):
        config, _ = station_from_legacy(LEGACY)
        sis1, sis2 = config.roles["sis1"], config.roles["sis2"]
        assert sis1.instrument == sis2.instrument == "sis_block_1"
        assert (sis1.channel, sis2.channel) == ("DEV4", "DEV2")
        assert sis2.attributes == {
            "offset_voltage": -0.000187,
            "offset_current": -1.3e-06,
        }
        assert sis1.metadata["calibration_coefficients"] == {"VoltageStep": 1e-05}
        assert config.roles["sis2_ctrl"].accessor == "ctrl"
        block = config.instruments["sis_block_1"].connection
        assert block.read_termination is None and block.read_delay == 0.05

    def test_imported_station_runs_simulated(self):
        config, _ = station_from_legacy(LEGACY)
        with Station(config, simulate=True) as station:
            station["sis2"].set_voltage(2.5e-3)
            station["sis2_ctrl"].set_current(1e-3)
            assert station["sis2"].offset_voltage == -0.000187

    def test_without_state_defaults(self):
        config, _ = station_from_legacy(LEGACY, include_state_defaults=False)
        assert "power_meter_1" not in config.instruments

    def test_slug(self):
        assert slug("Rohde Schwarz VNA ZVA 67 1") == "rohde_schwarz_vna_zva_67_1"
        assert slug("1st") == "i_1st"


class TestCli:
    def test_show(self, capsys):
        assert main(["show", str(EXAMPLE)]) == 0
        out = capsys.readouterr().out
        assert "lo_generator" in out and "lo_generator -> scaled_frequency" in out
        assert "Identifiable" not in out

    def test_check_simulated(self, capsys):
        assert main(["check", str(EXAMPLE), "--simulate", "--roles", "lo", "load"]) == 0
        out = capsys.readouterr().out
        assert "ok   lo: Switchable, FrequencySource, PowerLevel" in out
        assert "ok   load: LoadSwitch" in out

    def test_check_reports_failures(self, tmp_path, capsys):
        profile = tmp_path / "bad.yaml"
        profile.write_text(
            "name: bad\ninstruments:\n  gen: {driver: sim.signal_generator}\n"
            "roles:\n  lo: {instrument: gen, channel: 1}\n",
            encoding="utf-8",
        )
        assert main(["check", str(profile), "--simulate"]) == 1
        assert "FAIL lo" in capsys.readouterr().out

    @pytest.mark.skipif(
        __import__("importlib").util.find_spec("PySide6") is None,
        reason="legacy settings.ini needs PySide6",
    )
    def test_import_legacy_settings_file(self, tmp_path):
        from PySide6.QtCore import QSettings

        settings_path = tmp_path / "settings.ini"
        settings = QSettings(str(settings_path), QSettings.IniFormat)
        for section, entries in LEGACY.items():
            settings.setValue(f"Configs/{section}", entries)
        settings.sync()

        output = tmp_path / "lab.yaml"
        assert main(["import-legacy", str(settings_path), "-o", str(output)]) == 0
        config = load_station(output)
        assert config.roles["sis2"].attributes["offset_voltage"] == -0.000187
        assert config.instruments["signal_generator_2"].connection.gpib == 18

    def test_console_script_entry(self):
        result = subprocess.run(
            [sys.executable, "-m", "thzdaq_core.station.cli", "show", str(EXAMPLE)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0 and "sis_block" in result.stdout


def test_core_does_not_import_gui():
    code = (
        "import sys, thzdaq_core.station, thzdaq_core.station.cli, "
        "thzdaq_core.station.legacy;"
        "print(sorted(m for m in sys.modules "
        "if m.split('.')[0] in ('PySide6', 'pyqtgraph', 'store', 'interface')))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
