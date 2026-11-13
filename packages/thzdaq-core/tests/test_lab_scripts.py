"""Scripts the daemon runs apart from any terminal, and what a person allowed
them in advance (contract: LocalLab and RemoteLab)."""

import copy
import sys
from pathlib import Path

import pytest
from lab_helpers import Window, bodies, calling, wait_for
from thzdaq_api.daemon import (
    GetDaemonStatus,
    SetDaemonSettings,
    StopDaemon,
    StopMode,
)
from thzdaq_api.devices import RawCommand, ReadDevice, SetQuantity
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ScriptEnded, ScriptOutput, ScriptStarted
from thzdaq_api.measurement_file import ALLOWED, read_measurement
from thzdaq_api.measurements import StartMeasurement, WaitMeasurement
from thzdaq_api.operation import Rights
from thzdaq_api.origins import AGENT_CLI, GUI, script
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE
from thzdaq_api.rights import Decision
from thzdaq_api.scripts import (
    Grant,
    ListScripts,
    ReadScriptLog,
    StartScript,
    StopScript,
)
from thzdaq_api.sessions import EndSession, RestoreOnExit, StartSession
from thzdaq_api.station import GetStation, UpdateStation
from thzdaq_core.application.handlers.scripts import NOTHING_IN_ADVANCE

PYTHON = (sys.executable,)
LIMITS = {
    ref: {"voltage_set": {"min": -5e-3, "max": 5e-3, "warn_max": 4e-3}}
    for ref in ("sis_bias_1", "sis_bias_2")
}
SLOW = "import time\ntime.sleep(60)\n"
IV = dict(
    procedure=CURRENT_VS_VOLTAGE,
    parameters={
        "voltage": {"start": 0, "stop": 0.001, "points": 3},
        "settle_time": 0,
        "first_point_delay": 0,
    },
    devices={"bias": "sis_bias_1"},
)


@pytest.fixture
def quick_stop(lab):
    """A stopped script that ignores the cancel is ended soon."""
    lab.assembled.scripts.grace = 0.2


def written(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def run(lab, folder, name, text, **given):
    return lab.call(
        StartScript(
            path=str(written(folder, name, text)),
            python=PYTHON,
            workspace=str(folder),
            **given,
        )
    )


def ended(lab, id):
    wait_for(
        lambda: next(s for s in lab.call(ListScripts()) if s.id == id).status
        != "running",
        timeout=10,
    )
    return next(s for s in lab.call(ListScripts()) if s.id == id)


def bias_now(lab):
    reading = lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",)))
    return reading.values["voltage_set"]


def test_a_script_runs_apart_and_prints_into_its_log(lab, tmp_path):
    text = (
        "import os, sys\n"
        "print('hello', sys.argv[1:], os.getcwd())\n"
        "print(os.environ['THZDAQ_SCRIPT_ID'], os.environ['THZDAQ_SIMULATE'])\n"
        "print(os.environ['THZDAQ_WORKSPACE'])\n"
    )
    started = run(lab, tmp_path, "hello.py", text, arguments=("a", "b"))
    assert started.status == "running" and started.pid
    assert started.origin == script("hello", started.id)
    assert started.log == str(tmp_path / "data" / "scripts" / f"{started.id}.log")
    done = ended(lab, started.id)
    assert (done.status, done.exit_code, done.pid) == ("exited", 0, None)
    log = lab.call(ReadScriptLog(id=started.id))
    assert not log.running and log.next == Path(started.log).stat().st_size
    assert log.text.splitlines() == [
        f"hello ['a', 'b'] {tmp_path.resolve()}",
        f"{started.id} 1",  # its daemon simulates
        str(tmp_path.resolve()),  # where its measurements go
    ]
    rest = lab.call(ReadScriptLog(id=started.id, since=log.next))
    assert rest.text == "" and rest.next == log.next


def test_clients_hear_a_script_start_print_and_end(lab, tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    heard = []
    stop = lab.subscribe(heard.append)
    try:
        text = (
            "import time\n"
            "print('Привет, стенд')\n"
            "time.sleep(0.5)\n"  # a second part, told while it runs
            "print('bye')\n"
            "raise SystemExit(3)\n"
        )
        started = run(lab, tmp_path, "talk.py", text)
        done = ended(lab, started.id)
        wait_for(lambda: bodies(heard, ScriptEnded))
    finally:
        stop()
    told = [
        b for b in (event.body for event in heard)
        if isinstance(b, (ScriptStarted, ScriptOutput, ScriptEnded))
    ]  # fmt: skip
    assert told[0] == ScriptStarted(started) and told[-1] == ScriptEnded(done)
    assert (done.status, done.exit_code) == ("exited", 3)
    parts = told[1:-1]
    assert len(parts) >= 2 and all(p.id == started.id for p in parts)
    assert [p.since for p in parts[1:]] == [p.next for p in parts[:-1]]
    log = lab.call(ReadScriptLog(id=started.id))
    assert "".join(p.text for p in parts) == log.text == "Привет, стенд\nbye\n"
    assert parts[-1].next == log.next


def test_a_number_is_not_given_twice_in_a_folder(lab, tmp_path):
    (tmp_path / "data" / "scripts").mkdir(parents=True)
    (tmp_path / "data" / "scripts" / "7.log").write_text("an older daemon's\n")
    assert run(lab, tmp_path, "a.py", "pass\n").id == 8
    assert run(lab, tmp_path, "b.py", "pass\n").id == 9


def test_what_cannot_start_is_refused(lab, tmp_path):
    for operation, code in (
        (StartScript(path="nothing.py", python=PYTHON, workspace=str(tmp_path)),
         ErrorCode.INVALID_ARGUMENTS),
        (StartScript(path=str(written(tmp_path, "a.py", "")), python=("no-python",),
                     workspace=str(tmp_path)),
         ErrorCode.INVALID_ARGUMENTS),
        (StartScript(path=str(tmp_path / "a.py"), python=PYTHON,
                     allow=(Grant("set", "nothing_1"),)),
         ErrorCode.NOT_FOUND),
        (StartScript(path=str(tmp_path / "a.py"), python=PYTHON,
                     allow=(Grant("sweep", "sis_bias_1"),)),
         ErrorCode.INVALID_ARGUMENTS),
    ):  # fmt: skip
        with pytest.raises(LabError) as caught:
            lab.call(operation)
        assert caught.value.code == code


def test_a_running_script_keeps_the_daemon_until_it_is_stopped(
    lab, tmp_path, quick_stop
):
    started = run(lab, tmp_path, "slow.py", SLOW)
    assert [s.id for s in lab.call(GetDaemonStatus()).scripts] == [started.id]
    with pytest.raises(LabError) as caught:
        lab.call(StopDaemon(mode=StopMode.GRACEFUL))
    assert caught.value.code == ErrorCode.CONFLICT and "slow" in caught.value.message
    stopped = lab.call(StopScript(id=started.id))
    assert stopped.status == "stopped" and stopped.ended
    assert not lab.call(GetDaemonStatus()).scripts


def test_stopping_cancels_its_measurements_and_restores(
    lab, lab_as, tmp_path, quick_stop
):
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    started = run(lab, tmp_path, "slow.py", SLOW, allow=(Grant("set", "sis_bias_1"),))
    itself = lab_as(started.origin, "script")
    session = itself.call(StartSession(title="scan", devices=("sis_bias_1",)))
    itself.call(RestoreOnExit(id=session.id, ref="sis_bias_1", key="voltage_set"))
    itself.call(
        SetQuantity(
            ref="sis_bias_1", key="voltage_set", value="3mV", session=session.id
        )
    )
    lab.call(StopScript(id=started.id))
    gone = lab.call(WaitMeasurement(id=session.id, timeout=5))
    assert gone.status == "interrupted" and "stopped" in gone.error
    assert bias_now(lab) == pytest.approx(1e-3)


def test_a_script_that_ends_ends_its_sessions_at_once(lab, lab_as, tmp_path):
    started = run(lab, tmp_path, "brief.py", "import time\ntime.sleep(0.5)\n")
    itself = lab_as(started.origin, "script")
    session = itself.call(StartSession(title="scan", silent=60))
    gone = lab.call(WaitMeasurement(id=session.id, timeout=10))
    assert gone.status == "interrupted" and "exited" in gone.error


def warned(lab):
    """Both SIS biases warn above 4 mV."""
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    profile["safety"] = {"limits": LIMITS}
    lab.call(UpdateStation(profile=profile))


def test_a_persons_script_has_the_persons_rights(lab, lab_as, tmp_path, quick_stop):
    text = "import os\nprint(os.environ.get('CLAUDECODE'))\n" + SLOW
    started = run(lab, tmp_path, "slow.py", text)  # the daemon's shell is an agent's
    assert started.origin == script("slow", started.id) and started.by == "test"
    wait_for(lambda: lab.call(ReadScriptLog(id=started.id)).text)
    assert lab.call(ReadScriptLog(id=started.id)).text == "None\n"
    itself = lab_as(started.origin, "script")
    itself.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    session = itself.call(StartSession(title="scan", devices=("sis_bias_2",)))
    itself.call(EndSession(id=session.id))
    run_ = itself.call(StartMeasurement(**IV))
    assert lab.call(WaitMeasurement(id=run_.id, timeout=10)).status == "completed"
    with pytest.raises(LabError) as caught:  # dangerous: nobody answers
        itself.call(SetQuantity(ref="sis_bias_1", key="active", value=False))
    assert caught.value.code == ErrorCode.DENIED
    lab.call(StopScript(id=started.id))


def test_what_a_script_was_allowed_goes_without_a_person(
    lab, lab_as, tmp_path, quick_stop
):
    warned(lab)
    started = run(
        lab, tmp_path, "slow.py", SLOW,
        allow=(Grant("set", "sis_bias_1"), Grant("run", CURRENT_VS_VOLTAGE)),
    )  # fmt: skip
    itself = lab_as(started.origin, "script")
    # Beyond the warn range: what was allowed goes, the rest waits for a person
    itself.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="4.5mV"))
    run_ = itself.call(StartMeasurement(**IV))
    noted = read_measurement(lab.call(WaitMeasurement(id=run_.id, timeout=10)).path)
    assert noted.metadata[ALLOWED][0]["allow"] == [
        "set:sis_bias_1",
        f"run:{CURRENT_VS_VOLTAGE}",
    ]
    refused = [
        SetQuantity(ref="sis_bias_2", key="voltage_set", value="4.5mV"),
        SetQuantity(ref="sis_bias_1", key="active", value=False),  # dangerous
    ]
    for operation in refused:  # nobody answers
        with pytest.raises(LabError) as caught:
            itself.call(operation)
        assert caught.value.code == ErrorCode.DENIED, operation
    lab.call(StopScript(id=started.id))
    with pytest.raises(LabError) as caught:  # only while it runs
        itself.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="4.6mV"))
    assert caught.value.code == ErrorCode.DENIED


def test_what_a_script_was_allowed_is_in_a_run_that_ends_at_once(
    lab, lab_as, tmp_path, quick_stop, monkeypatch
):
    """A short run may be saved before its start returns: what its script
    was allowed is noted as it starts, not after."""
    from thzdaq_core.application.runs import Runs

    start = Runs.start

    def ended_first(self, *args, **kwargs):
        info = start(self, *args, **kwargs)
        if info.id:  # not a dry run, which a check makes
            self.wait(info.id, timeout=10)
        return info

    started = run(
        lab, tmp_path, "slow.py", SLOW, allow=(Grant("run", CURRENT_VS_VOLTAGE),)
    )
    itself = lab_as(started.origin, "script")
    monkeypatch.setattr(Runs, "start", ended_first)
    run_ = itself.call(StartMeasurement(**IV))
    noted = read_measurement(lab.call(WaitMeasurement(id=run_.id, timeout=0)).path)
    assert noted.metadata[ALLOWED] == [
        {
            "script": started.id, "by": "test",
            "allow": [f"run:{CURRENT_VS_VOLTAGE}"], "share": [],
        }  # fmt: skip
    ]
    lab.call(StopScript(id=started.id))


def test_a_script_shares_what_it_was_told_to(lab, lab_as, tmp_path, quick_stop):
    sweep = lab.call(StartSession(title="sweep", exclusive=("sis_bias_1",)))
    started = run(
        lab, tmp_path, "slow.py", SLOW,
        allow=(Grant("set", "sis_bias_1"),), share=("sis_bias_1",),
    )  # fmt: skip
    itself = lab_as(started.origin, "script")
    session = itself.call(StartSession(title="scan", devices=("sis_bias_1",)))
    assert session.conflicts and session.conflicts[0]["run"] == sweep.id
    itself.call(EndSession(id=session.id))
    lab.call(EndSession(id=sweep.id))
    lab.call(StopScript(id=started.id))


def test_an_agents_script_is_allowed_by_a_person(lab_as, tmp_path):
    window = Window(lab_as(GUI))
    try:
        agent = lab_as("mcp:claude")
        operation = StartScript(
            path=str(written(tmp_path, "scan.py", "pass\n")),
            python=PYTHON,
            workspace=str(tmp_path),
            allow=(Grant("set", "sis_bias_1"),),
        )
        thread, done = calling(agent, operation)
        approval = window.asked()
        assert approval.title.endswith("scan.py")
        assert NOTHING_IN_ADVANCE in approval.text
        window.answer(allowed=False, text="not tonight")
        thread.join(5)
        assert done["error"].code == ErrorCode.DENIED
    finally:
        window.stop()


def test_an_agents_script_has_the_agents_rights(lab, lab_as, tmp_path, quick_stop):
    lab.call(SetDaemonSettings(agents={Rights.RUN: Decision.ALLOW}))
    text = "import os\nprint(os.environ.get('THZDAQ_AGENT'))\n" + SLOW
    started = lab_as(AGENT_CLI).call(
        StartScript(
            path=str(written(tmp_path, "slow.py", text)),
            python=PYTHON,
            workspace=str(tmp_path),
            allow=(Grant("set", "sis_bias_1"),),
            share=("sis_bias_1",),
        )
    )
    assert started.origin == script("slow", started.id, by_agent=True)
    assert (started.by, started.allow, started.share) == (AGENT_CLI, (), ())
    wait_for(lambda: lab.call(ReadScriptLog(id=started.id)).text)
    assert lab.call(ReadScriptLog(id=started.id)).text == "1\n"
    # Asked as the agent's (nobody answers), whatever it calls itself
    for origin in (started.origin, script("slow", started.id)):
        itself = lab_as(origin, "script")
        for operation in (
            SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"),
            RawCommand(instrument="sis_block_1", command="DEV4:OFF"),
        ):
            with pytest.raises(LabError) as caught:
                itself.call(operation)
            assert caught.value.code == ErrorCode.DENIED, (origin, operation)
    lab.call(StopScript(id=started.id))
