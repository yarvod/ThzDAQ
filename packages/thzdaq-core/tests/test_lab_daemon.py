"""The daemon's own operations through LocalLab: its status, stopping it."""

import copy
import os
import threading

import pytest
from thzdaq_api.daemon import GetDaemonStatus, RestartDaemon, StopDaemon, StopMode
from thzdaq_api.devices import ReadDevice, SetQuantity, SubscribePoll
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import StartMeasurement, WaitMeasurement
from thzdaq_api.procedures import MONITOR_VALUES_VS_TIME
from thzdaq_api.station import GetStation, UpdateStation
from lab_helpers import wait_for

FOREVER = {"watch": ["power_meter_1/power"], "interval": 0.02, "duration": 0.0}


def control(lab):
    return lab.assembled.daemon.control


def test_the_status_tells_what_the_daemon_holds(lab):
    lab.call(ReadDevice(ref="power_meter_1"))
    lab.call(SubscribePoll(ref="power_meter_1", interval=5.0))
    run = lab.call(
        StartMeasurement(procedure=MONITOR_VALUES_VS_TIME, parameters=FOREVER)
    )
    status = lab.call(GetDaemonStatus())
    assert status.process.pid == os.getpid() and status.process.simulate
    assert "power_meter_1" in status.opened
    assert [r.id for r in status.runs] == [run.id]
    assert [(p.ref, p.interval) for p in status.polls] == [("power_meter_1", 5.0)]
    assert "power_meter_1" in {lane.instrument for lane in status.lanes}
    assert status.problems == () and status.seq > 0


def test_the_status_shows_a_lane_that_hangs(lab):
    """A job that does not end names its instrument among the problems, in the
    status and its heartbeat; once it ends, the problem goes."""
    service = lab.assembled.daemon
    service.stuck = 0.05  # a job running longer hangs
    answer = threading.Event()
    hangs = lambda meter: answer.wait(10)  # noqa: E731
    service.bench.submit("power_meter_1", hangs, lambda result, error: None)
    try:
        wait_for(lambda: lab.call(GetDaemonStatus()).problems)
        status = lab.call(GetDaemonStatus())
        (lane,) = [lane for lane in status.lanes if lane.instrument == "power_meter_1"]
        assert lane.stuck and lane.current
        assert status.problems == (
            f"power_meter_1: {lane.current} runs for {lane.busy_for:.0f} s",
        )
        assert service.heartbeat(status.seq).problems
    finally:
        answer.set()
    wait_for(lambda: not lab.call(GetDaemonStatus()).problems)


def test_a_graceful_stop_is_refused_while_measurements_run(lab):
    run = lab.call(
        StartMeasurement(procedure=MONITOR_VALUES_VS_TIME, parameters=FOREVER)
    )
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
    run = lab.call(
        StartMeasurement(procedure=MONITOR_VALUES_VS_TIME, parameters=FOREVER)
    )
    lab.call(RestartDaemon(mode=StopMode.CANCEL))
    assert lab.call(WaitMeasurement(id=run.id, timeout=0)).status == "cancelled"
    reading = lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",)))
    assert reading.values["voltage_set"] == 0.0
    assert control(lab).stopped.is_set() and control(lab).restart


def test_settings_are_kept_and_the_log_read(lab):
    from thzdaq_api.daemon import GetDaemonSettings, ReadDaemonLog, SetDaemonSettings

    assert lab.call(SetDaemonSettings(idle_timeout=300.0)).idle_timeout == 300.0
    assert lab.call(GetDaemonSettings()).idle_timeout == 300.0
    with pytest.raises(LabError) as caught:
        lab.call(SetDaemonSettings(idle_timeout=-1.0))
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    assert isinstance(lab.call(ReadDaemonLog(lines=5)), tuple)


def test_a_lane_is_reset_and_its_instrument_works_again(lab):
    from thzdaq_api.daemon import ResetLane

    lab.call(ReadDevice(ref="power_meter_1"))  # it has a lane now
    assert lab.call(ResetLane(instrument="power_meter_1")) is True
    assert "power" in lab.call(ReadDevice(ref="power_meter_1")).values
    with pytest.raises(LabError) as caught:
        lab.call(ResetLane(instrument="power_meter_9"))
    assert caught.value.code == ErrorCode.NOT_FOUND
