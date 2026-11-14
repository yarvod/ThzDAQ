"""A grid's angle survives a restart of the daemon (its state-sim.json next to
daemon-sim.json); one that was moving when the daemon stopped is unknown until
it is zeroed."""

import json

import pytest
from test_process import gone, start
from thzdaq_api.devices import CallAction, ReadDevice, SetQuantity
from thzdaq_api.errors import LabError
from thzdaq_api.host import DaemonFiles
from thzdaq_api.daemon import StopDaemon

GRID = "grid_1"


def stopped(lab):
    lab.call(StopDaemon())
    gone(lab.host.pid, DaemonFiles.of(True))


def test_the_angle_survives_a_restart(home):
    lab = start(home)
    lab.call(SetQuantity(ref=GRID, key="angle", value="30"))
    stopped(lab)
    record = json.loads((home / "state-sim.json").read_text())[GRID]
    assert record["state"] == {"angle": 30.0}
    assert not (home / "state.json").exists()  # the bench's own is apart

    again = start(home)
    assert again.host.pid != lab.host.pid
    assert again.call(ReadDevice(ref=GRID)).values == {"angle": 30.0}
    stopped(again)


def test_a_grid_left_moving_asks_for_a_zero(home):
    moving = {"angle": 30.0, "moving_to": 60.0}
    record = {"driver": "arduino.grid", "state": moving}
    (home / "state-sim.json").write_text(json.dumps({GRID: record}))
    lab = start(home)
    with pytest.raises(LabError, match="set its zero"):
        lab.call(ReadDevice(ref=GRID))
    lab.call(CallAction(ref=GRID, action="zero"))
    assert lab.call(ReadDevice(ref=GRID)).values == {"angle": 0.0}
    stopped(lab)
    assert json.loads((home / "state-sim.json").read_text())[GRID]["state"] == {
        "angle": 0.0
    }
