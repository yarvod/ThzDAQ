"""What the program keeps of instruments it alone knows (a grid's angle): the
JSON file of the InstrumentStates port, a station that gives it back when an
instrument opens, and the angle through measurement cycles on the simulated
example bench: completed, cancelled, aborted, then zeroed."""

import json
import logging
import shutil
import threading
import time
from pathlib import Path

import pytest
from lab_helpers import wait_for
from thzdaq_api.devices import CallAction, ReadDevice, SetQuantity
from thzdaq_api.errors import LabError
from thzdaq_api.measurements import (
    AbortMeasurement,
    CancelMeasurement,
    StartMeasurement,
    WaitMeasurement,
)
from thzdaq_api.measurement_file import read_measurement
from thzdaq_api.procedures import GRID_CURRENT_ANGLE, MONITOR_TIME
from thzdaq_instruments.angle import AngleUnknown
from thzdaq_instruments.drivers import ArduinoGrid

from thzdaq_core.adapters.instrument_states import JsonInstrumentStates
from thzdaq_core.adapters.yaml_profiles import load_station
from thzdaq_core.application.kept import KeptStates
from thzdaq_core.domain.station.station import Station

GRID = "grid_1"
PROFILE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


def station(path, profile=PROFILE):
    """The simulated example bench, keeping its instruments' state in path."""
    kept = KeptStates(JsonInstrumentStates(path))
    return Station(
        load_station(profile), pause=time.sleep, simulate=True, on_open=kept.opened
    )


class TestStateFile:
    def test_records_by_instrument_are_kept_whole(self, tmp_path):
        path = tmp_path / "state.json"
        states = JsonInstrumentStates(path)
        assert states.get(GRID) is None
        states.put(GRID, {"driver": "arduino.grid", "state": {"angle": 30.0}})
        states.put("grid_2", {"driver": "arduino.grid", "state": {"angle": 5.0}})
        assert json.loads(path.read_text())[GRID]["state"] == {"angle": 30.0}
        assert not path.with_suffix(".partial").exists()
        again = JsonInstrumentStates(path)
        assert again.get("grid_2") == {
            "driver": "arduino.grid",
            "state": {"angle": 5.0},
        }

    def test_a_broken_file_keeps_nothing_and_says_so(self, tmp_path, caplog):
        path = tmp_path / "state.json"
        path.write_text("{not json")
        with caplog.at_level(logging.ERROR):
            assert JsonInstrumentStates(path).get(GRID) is None
        assert "not read" in caplog.text

    def test_a_failed_write_is_logged_not_raised(self, tmp_path, caplog):
        states = JsonInstrumentStates(tmp_path / "gone" / "state.json")
        with caplog.at_level(logging.ERROR):
            states.put(GRID, {"driver": "arduino.grid", "state": {"angle": 1.0}})
        assert "not kept" in caplog.text
        assert states.get(GRID)["state"] == {"angle": 1.0}

    def test_moves_from_several_threads_leave_a_whole_file(self, tmp_path):
        path = tmp_path / "state.json"
        states = JsonInstrumentStates(path)

        def move(name):
            for angle in range(50):
                states.put(name, {"driver": "sim", "state": {"angle": float(angle)}})

        threads = [threading.Thread(target=move, args=(f"grid_{i}",)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        found = json.loads(path.read_text())
        assert {found[f"grid_{i}"]["state"]["angle"] for i in range(4)} == {49.0}


class TestStation:
    def test_the_angle_comes_back_when_the_grid_opens_again(self, tmp_path):
        path = tmp_path / "state-sim.json"
        with station(path) as first:
            first.device(GRID).rotate_to(30.0)
        record = json.loads(path.read_text())[GRID]
        assert record == {"driver": ArduinoGrid.driver_key, "state": {"angle": 30.0}}
        with station(path) as second:
            assert second.device(GRID).get_angle() == 30.0

    def test_a_grid_that_was_moving_must_be_zeroed(self, tmp_path):
        path = tmp_path / "state-sim.json"
        moving = {"angle": 30.0, "moving_to": 60.0}
        JsonInstrumentStates(path).put(
            GRID, {"driver": ArduinoGrid.driver_key, "state": moving}
        )
        with station(path) as bench:
            grid = bench.device(GRID)
            with pytest.raises(AngleUnknown, match="set its zero"):
                grid.get_angle()
            with pytest.raises(AngleUnknown):
                grid.rotate_to(10.0)
            position = bench.instrument(GRID).position
            grid.zero()
            assert grid.get_angle() == 0.0
            assert bench.instrument(GRID).position == position  # nothing moved
        assert json.loads(path.read_text())[GRID]["state"] == {"angle": 0.0}

    def test_a_record_of_another_driver_is_not_applied(self, tmp_path):
        path = tmp_path / "state-sim.json"
        JsonInstrumentStates(path).put(
            GRID, {"driver": "other.rotator", "state": {"angle": 30.0}}
        )
        with station(path) as bench:
            assert bench.device(GRID).get_angle() == 0.0

    def test_an_instrument_reopened_after_an_abort_keeps_its_angle(self, tmp_path):
        with station(tmp_path / "state-sim.json") as bench:
            bench.device(GRID).rotate_to(45.0)
            bench.abort([GRID])  # its own connection (HTTP): closed, reopened on use
            assert not bench.is_open(GRID)
            assert bench.device(GRID).get_angle() == 45.0


@pytest.fixture
def kept_lab(tmp_path):
    """The lab fixture's bench, keeping its instruments' state as the daemon does."""
    from thzdaq_api.custom import LIBRARY
    from thzdaq_api.lanes import Lanes
    from thzdaq_api.measurements import DATA
    from thzdaq_core.adapters.json_store import MeasurementStore
    from thzdaq_core.adapters.library import FolderLibrary
    from thzdaq_core.adapters.processes import Processes
    from thzdaq_core.adapters.yaml_profiles import YamlProfiles
    from thzdaq_core.application.assembly import assemble
    from thzdaq_core.application.bench import Bench
    from thzdaq_core.application.local import LocalControl, LocalLab
    from thzdaq_core.application.workspaces import Workspaces

    profile = tmp_path / "bench.yaml"
    shutil.copy(PROFILE, profile)
    lanes = Lanes()
    bench = Bench(station(tmp_path / "state-sim.json", profile), lanes, str(profile))
    assembled = assemble(
        bench, Workspaces(tmp_path, tmp_path / DATA, MeasurementStore), YamlProfiles(),
        LocalControl(True), Processes(), FolderLibrary(tmp_path / LIBRARY),
    )  # fmt: skip
    yield LocalLab(assembled, origin="test", kind="test")
    assembled.close()
    lanes.stop()
    bench.station.close()


def angle(lab):
    return lab.call(ReadDevice(ref=GRID)).values["angle"]


def kept(lab, tmp_path):
    return json.loads((tmp_path / "state-sim.json").read_text())[GRID]["state"]


def scan(lab, speed, settle=0.0):
    parameters = {
        "angle": {"start": 0.0, "stop": 90.0, "points": 4},
        "grid_speed": speed,
        "settle_time": settle,
    }
    devices = {"grid": GRID, "bias": "sis_bias_1"}
    return lab.call(
        StartMeasurement(
            procedure=GRID_CURRENT_ANGLE, parameters=parameters, devices=devices
        )
    )


def ended(lab, run):
    info = lab.call(WaitMeasurement(id=run.id, timeout=10))
    assert info.status != "running"
    return info


class TestMeasurementCycles:
    def test_the_angle_is_counted_through_runs_and_comes_back(self, kept_lab, tmp_path):
        lab = kept_lab
        lab.call(SetQuantity(ref=GRID, key="angle", value=20.0))
        for _ in range(2):
            assert ended(lab, scan(lab, 1e6)).status == "completed"
            assert angle(lab) == 20.0
            assert kept(lab, tmp_path) == {"angle": 20.0}

    def test_a_cancelled_run_puts_the_grid_back(self, kept_lab, tmp_path):
        lab = kept_lab
        lab.call(SetQuantity(ref=GRID, key="angle", value=10.0))
        run = scan(lab, 1e6, settle=0.2)
        wait_for(lambda: angle(lab) != 10.0, timeout=5)
        lab.call(CancelMeasurement(id=run.id))
        assert ended(lab, run).status == "cancelled"
        assert angle(lab) == 10.0 and kept(lab, tmp_path) == {"angle": 10.0}

    def test_an_aborted_run_reopens_the_grid_where_it_stands(self, kept_lab, tmp_path):
        lab = kept_lab
        lab.call(SetQuantity(ref=GRID, key="angle", value=10.0))
        run = scan(lab, 1e6, settle=0.2)
        wait_for(lambda: angle(lab) != 10.0, timeout=5)
        lab.call(AbortMeasurement(id=run.id))
        ended(lab, run)
        assert angle(lab) == kept(lab, tmp_path)["angle"]

    def test_zero_is_an_action_and_the_angle_is_read_anew(self, kept_lab, tmp_path):
        lab = kept_lab
        lab.call(SetQuantity(ref=GRID, key="angle", value=30.0))
        lab.call(CallAction(ref=GRID, action="zero"))
        assert angle(lab) == 0.0 and kept(lab, tmp_path) == {"angle": 0.0}
        snapshot = lab.assembled.runs.bench.station.device(GRID).setpoints
        assert "angle" not in snapshot

    def test_an_unknown_angle_asks_for_a_zero_in_the_reading(self, kept_lab):
        lab = kept_lab
        grid = lab.assembled.runs.bench.station.instrument(GRID)
        grid.restore_state({"angle": 30.0, "moving_to": 45.0})
        with pytest.raises(LabError, match="set its zero"):
            angle(lab)
        lab.call(CallAction(ref=GRID, action="zero"))
        assert angle(lab) == 0.0

    def test_the_angle_is_watched_over_time(self, kept_lab):
        lab = kept_lab
        lab.call(SetQuantity(ref=GRID, key="angle", value=15.0))
        parameters = {"watch": [GRID], "interval": 0.01, "duration": 0.1}
        run = lab.call(StartMeasurement(procedure=MONITOR_TIME, parameters=parameters))
        assert ended(lab, run).status == "completed"
        samples = read_measurement(run.path).records("samples")
        assert samples and {(r["quantity"], r["value"]) for r in samples} == {
            ("Angle", 15.0)
        }
