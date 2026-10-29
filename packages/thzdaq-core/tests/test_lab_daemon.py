"""The daemon's own operations through LocalLab: its status, stopping it."""

import copy
import os

import pytest
from thzdaq_api.daemon import GetDaemonStatus, RestartDaemon, StopDaemon, StopMode
from thzdaq_api.devices import ReadDevice, SetQuantity, SubscribePoll
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import StartMeasurement, WaitMeasurement
from thzdaq_api.procedures import MONITOR_TIME
from thzdaq_api.station import GetStation, UpdateStation

FOREVER = {"watch": ["power_meter_1/power"], "interval": 0.02, "duration": 0.0}


def control(lab):
    return lab.assembled.daemon.control


def test_the_status_tells_what_the_daemon_holds(lab):
    lab.call(ReadDevice(ref="power_meter_1"))
    lab.call(SubscribePoll(ref="power_meter_1", interval=5.0))
    run = lab.call(StartMeasurement(procedure=MONITOR_TIME, parameters=FOREVER))
    status = lab.call(GetDaemonStatus())
    assert status.process.pid == os.getpid() and status.process.simulate
    assert "power_meter_1" in status.opened
    assert [r.id for r in status.runs] == [run.id]
    assert [(p.ref, p.interval) for p in status.polls] == [("power_meter_1", 5.0)]
    assert "power_meter_1" in {lane.instrument for lane in status.lanes}
    assert status.problems == () and status.seq > 0


def test_a_graceful_stop_is_refused_while_measurements_run(lab):
    run = lab.call(StartMeasurement(procedure=MONITOR_TIME, parameters=FOREVER))
    with pytest.raises(LabError) as caught:
        lab.call(StopDaemon())
    assert caught.value.code == ErrorCode.CONFLICT
    assert f"#{run.id}" in caught.value.message
    assert not control(lab).stopped.is_set()


def test_a_cancel_ends_the_measurements_and_goes_safe(lab):
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    profile["safety"] = {"safe_state": {"sis_bias_1": {"voltage_set": 0}}}
    lab.call(UpdateStation(profile=profile))
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="2 mV"))
    run = lab.call(StartMeasurement(procedure=MONITOR_TIME, parameters=FOREVER))
    lab.call(RestartDaemon(mode=StopMode.CANCEL))
    assert lab.call(WaitMeasurement(id=run.id, timeout=0)).status == "cancelled"
    reading = lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",)))
    assert reading.values["voltage_set"] == 0.0
    assert control(lab).stopped.is_set() and control(lab).restart
