"""Raw commands: what a driver does not wrap yet, sent to an instrument as
typed. A query is free to people and their scripts and asked for agents; a
write, which no limit checks, is refused to agents and their scripts, asked
for a person's script unless allowed in advance, conflicts with another's sweep, is noted and leaves the
instrument's devices unknown until read again (contract: LocalLab and
RemoteLab)."""

import logging

import pytest
from lab_helpers import Window, bodies, calling, wait_for
from test_lab_leases import SLOW_IV, finish
from test_lab_scripts import SLOW, quick_stop, run  # noqa: F401
from thzdaq_api.devices import UNCHECKED, ListDevices, RawCommand, ReadDevice
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import GetSnapshot, RawSent, Values
from thzdaq_api.measurement_file import (
    ALLOWED,
    CONFLICTS,
    INTERACTIONS,
    read_measurement,
)
from thzdaq_api.measurements import StartMeasurement
from thzdaq_api.origins import GUI, script
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE, MONITOR_VALUES_VS_TIME
from thzdaq_api.scripts import Grant, StartScript
from thzdaq_api.sessions import EndSession, StartSession

AGENT = "mcp:claude"
BLOCK = "sis_block_1"  # a SIS block: sis_bias_1 and the others are on it
IDENTITY = "THZDAQ,SimSisBlock,0,1.0"
WRITE = "DEV4:OFF"  # a simulator takes it without effect


def raw(command, instrument=BLOCK, **given):
    return RawCommand(instrument=instrument, command=command, **given)


def refused(lab, operation):
    with pytest.raises(LabError) as caught:
        lab.call(operation)
    return caught.value


@pytest.fixture
def window(lab_as):
    window = Window(lab_as(GUI))
    yield window
    window.stop()


def test_a_query_answers_and_changes_nothing(lab, caplog):
    heard = []
    lab.subscribe(heard.append)
    with caplog.at_level(logging.INFO):
        reply = lab.call(raw("*IDN?"))
    assert (reply.answer, reply.unknown) == (IDENTITY, ())
    (sent,) = bodies(heard, RawSent)
    assert (sent.command, sent.answer, sent.origin) == ("*IDN?", IDENTITY, "test")
    assert f"raw {BLOCK} '*IDN?' by test: '{IDENTITY}'" in caplog.text


def test_a_write_leaves_the_devices_on_the_instrument_unknown_and_reads_them(lab):
    heard = []
    lab.subscribe(heard.append)
    reply = lab.call(raw(WRITE))
    on_block = {d.ref for d in lab.call(ListDevices()) if d.instrument == BLOCK}
    assert reply.answer is None and set(reply.unknown) == on_block
    assert "sis_bias_1" in on_block
    (sent,) = bodies(heard, RawSent)
    assert set(sent.unknown) == on_block
    wait_for(lambda: "sis_bias_1" in {body.ref for body in bodies(heard, Values)})
    assert heard.index(next(e for e in heard if isinstance(e.body, RawSent))) < min(
        heard.index(e) for e in heard if isinstance(e.body, Values)
    )


def test_a_write_may_read_an_answer_and_fail_half_way(lab):
    """A query without ? (Sumitomo $TEA...) is a write whose answer is read. A
    simulator has none: the write went, so the bias is not known any more."""
    lab.call(ReadDevice(ref="sis_bias_1"))
    assert "sis_bias_1" in lab.call(GetSnapshot()).values
    with pytest.raises(LabError) as caught:
        lab.call(raw(WRITE, answer=True))
    assert "a simulator answers only *IDN?" in str(caught.value)
    assert "sis_bias_1" not in lab.call(GetSnapshot()).values


def test_what_takes_no_raw_commands_is_refused(lab):
    assert refused(lab, raw("*IDN?", "chopper_1")).code == ErrorCode.NOT_ALLOWED
    device = refused(lab, raw("*IDN?", "sis_bias_1"))
    assert device.code == ErrorCode.NOT_FOUND and BLOCK in device.hint
    assert refused(lab, raw("*IDN?", "nothing")).code == ErrorCode.NOT_FOUND
    taking = {d.ref: d.raw for d in lab.call(ListDevices())}
    assert taking["sis_bias_1"] and taking[BLOCK] and not taking["chopper_1"]


def test_agents_never_write_raw_commands(lab, lab_as, window):
    heard = []
    lab.subscribe(heard.append)
    denied = refused(lab_as(AGENT), raw(WRITE, share=True))
    assert denied.code == ErrorCode.DENIED and not window.waiting()
    assert not bodies(heard, RawSent)


def test_an_agents_query_waits_for_a_person(lab_as, window):
    thread, done = calling(lab_as(AGENT), raw("*IDN?"))
    approval = window.asked()
    assert (approval.title, approval.text) == (f"{BLOCK} · raw query", "*IDN?")
    window.answer(allowed=True)
    thread.join(5)
    assert done["result"].answer == IDENTITY


def test_a_scripts_write_waits_for_a_person(lab_as, window):
    itself = lab_as(script("probe"), "script")
    assert itself.call(raw("*IDN?")).answer == IDENTITY  # a query: no person
    assert not window.waiting()
    thread, done = calling(itself, raw(WRITE))
    approval = window.asked()
    assert approval.title == f"{BLOCK} · raw write" and approval.text == WRITE
    assert UNCHECKED in approval.warning
    window.answer(allowed=True)
    thread.join(5)
    assert set(done["result"].unknown) >= {BLOCK, "sis_bias_1"}


def test_an_agents_script_writes_no_raw_command(lab_as, window):
    itself = lab_as(script("probe", by_agent=True), "script")
    assert refused(itself, raw(WRITE)).code == ErrorCode.DENIED
    thread, done = calling(itself, raw("*IDN?"))  # a query is asked
    assert window.asked().text == "*IDN?"
    window.answer(allowed=True)
    thread.join(5)
    assert done["result"].answer == IDENTITY


def test_a_script_allowed_raw_writes_goes_without_a_person(
    lab, lab_as, tmp_path, quick_stop  # noqa: F811
):
    started = run(lab, tmp_path, "slow.py", SLOW, allow=(Grant("raw", BLOCK),))
    itself = lab_as(started.origin, "script")
    assert itself.call(raw(WRITE)).answer is None  # no window: not asked
    other = refused(itself, raw(WRITE, "signal_generator_1"))
    assert other.code == ErrorCode.DENIED  # nobody answers for another instrument
    typo = refused(
        lab,
        StartScript(
            path=str(tmp_path / "slow.py"), python=("python",),
            allow=(Grant("raw", "chopper_1"),),
        ),
    )  # fmt: skip
    assert typo.code == ErrorCode.NOT_ALLOWED


def test_a_yes_in_a_session_lets_it_write_raw_commands_until_it_ends(lab_as, window):
    itself = lab_as(script("probe"), "script")
    run = itself.call(StartSession(title="probe", devices=("sis_bias_1",)))
    thread, done = calling(itself, raw(WRITE, session=run.id))
    approval = window.asked()
    assert f"#{run.id} writes to {BLOCK} without asking until it ends" in (
        approval.warning
    )
    window.answer(allowed=True)
    thread.join(5)
    assert "error" not in done
    assert itself.call(raw("DEV3:OFF", session=run.id)).unknown  # nobody asked
    assert not window.waiting()
    thread, done = calling(itself, raw(WRITE))  # outside it: asked again
    window.asked()
    window.answer(allowed=False)
    thread.join(5)
    assert done["error"].code == ErrorCode.DENIED
    ended = itself.call(EndSession(id=run.id))
    allowed = read_measurement(ended.path).metadata[ALLOWED]
    assert [(a["allow"], a["first"]) for a in allowed] == [([f"raw:{BLOCK}"], WRITE)]


def test_a_write_to_a_swept_instrument_conflicts_and_is_noted(lab):
    sweep = lab.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            parameters=SLOW_IV,
            devices={"bias": "sis_bias_1"},
        )
    )
    assert lab.call(raw("*IDN?")).answer == IDENTITY  # a query disturbs nothing
    conflict = refused(lab, raw(WRITE))
    assert conflict.code == ErrorCode.CONFLICT and f"#{sweep.id}" in str(conflict)
    lab.call(raw(WRITE, share=True))
    noted = read_measurement(finish(lab, sweep.id).path).metadata[CONFLICTS]
    assert [(n["by"], n["device"], n["raw"]) for n in noted] == [("test", BLOCK, WRITE)]


def test_a_write_is_noted_by_the_measurements_reading_the_instrument(lab):
    monitor = lab.call(
        StartMeasurement(
            procedure=MONITOR_VALUES_VS_TIME,
            parameters={"watch": ["power_meter_1"], "interval": 0.05},
        )
    )
    lab.call(raw("*CLS", "power_meter_1"))
    lab.call(ReadDevice(ref="power_meter_1"))
    noted = read_measurement(finish(lab, monitor.id).path).metadata[INTERACTIONS]
    assert [(n["device"], n["raw"]) for n in noted] == [("power_meter_1", "*CLS")]
