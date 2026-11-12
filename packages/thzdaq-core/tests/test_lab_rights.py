"""What agents may do is a setting of the daemon people change; some rules stay
whatever it says (contract: LocalLab and RemoteLab)."""

import copy

import pytest
from lab_helpers import Window, calling
from thzdaq_api.approvals import AnswerApproval
from thzdaq_api.daemon import GetDaemonSettings, SetDaemonSettings
from thzdaq_api.devices import CallAction, ListDevices, SafeState, SetQuantity
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.operation import Rights
from thzdaq_api.origins import GUI
from thzdaq_api.rights import AGENTS, Decision
from thzdaq_api.station import GetStation, UpdateStation

AGENT = "mcp:claude"
LIMITS = {"sis_bias_1": {"voltage_set": {"min": -5e-3, "max": 5e-3, "warn_max": 4e-3}}}


def bias(value):
    return SetQuantity(ref="sis_bias_1", key="voltage_set", value=value)


@pytest.fixture
def sets_alone(lab):
    """Agents may set alone; sis_bias_1 warns above 4 mV."""
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    profile["safety"] = {"limits": LIMITS}
    lab.call(UpdateStation(profile=profile))
    lab.call(SetDaemonSettings(agents={Rights.SET: Decision.ALLOW}))
    lab.call(bias("1mV"))
    return lab


@pytest.fixture
def window(lab_as):
    window = Window(lab_as(GUI))
    yield window
    window.stop()


def refused(call):
    with pytest.raises(LabError) as caught:
        call()
    return caught.value


def asked(lab_as, window, operation):
    """The agent's call waits for the window; refused there, what it read."""
    thread, done = calling(lab_as(AGENT), operation)
    approval = window.asked()
    window.answer(allowed=False)
    thread.join(5)
    assert done["error"].code == ErrorCode.DENIED
    return approval


def test_the_rights_of_agents_are_a_setting(lab):
    assert lab.call(GetDaemonSettings()).agents == AGENTS
    changed = lab.call(SetDaemonSettings(agents={Rights.RUN: Decision.ALLOW}))
    assert changed.agents == {**AGENTS, Rights.RUN: Decision.ALLOW}
    assert changed.idle_timeout == lab.call(GetDaemonSettings()).idle_timeout
    kept = lab.call(SetDaemonSettings(idle_timeout=30.0))
    assert kept.agents[Rights.RUN] == Decision.ALLOW and kept.idle_timeout == 30.0


def test_an_allowed_set_goes_without_a_person(sets_alone, lab_as):
    """No window: a set it had to ask for would be refused at once."""
    assert lab_as(AGENT).call(bias("1.5mV")).value == pytest.approx(1.5e-3)


def test_an_allowed_set_that_may_harm_is_still_asked(sets_alone, lab_as, window):
    beyond = asked(lab_as, window, bias("4.5mV"))
    assert "above warn_max 4 mV" in beyond.warning
    sets_alone.call(bias("0.1mV"))
    assert asked(lab_as, window, bias("2mV")).text == "100 µV → 2 mV (×20)"
    dangerous = SetQuantity(ref="sis_bias_1", key="active", value=False)
    assert asked(lab_as, window, dangerous).confirm == "sis_bias_1"


def test_a_dangerous_action_is_asked_typing_the_device_though_allowed(
    lab, lab_as, window
):
    """Agents may change devices alone; stopping the compressor still waits for
    a person who types its name: no setting lets it go without one."""
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    profile["instruments"]["compressor_1"] = {
        "driver": "sumitomo.f70_rest",
        "connection": {"kind": "http", "host": "10.0.0.5", "port": 21024},
    }
    lab.call(UpdateStation(profile=profile))
    lab.call(SetDaemonSettings(agents={Rights.SET: Decision.ALLOW}))
    stop = CallAction(ref="compressor_1", action="turn_off")
    approval = asked(lab_as, window, stop)
    assert approval.confirm == "compressor_1" and "warms up" in approval.warning


def test_people_choose_any_rights_but_the_fixed_ones(lab, lab_as):
    for fixed in (Rights.STATION, Rights.ANSWER):
        error = refused(
            lambda: lab.call(SetDaemonSettings(agents={fixed: Decision.ALLOW}))
        )
        assert error.code == ErrorCode.INVALID_ARGUMENTS
        assert lab.call(GetDaemonSettings()).agents[fixed] == Decision.DENY
    lab.call(
        SetDaemonSettings(
            agents={Rights.READ: Decision.DENY, Rights.DAEMON: Decision.ALLOW}
        )
    )
    agent = lab_as(AGENT)
    assert refused(lambda: agent.call(ListDevices())).code == ErrorCode.DENIED
    agent.call(SafeState())  # stopping stays allowed
    assert agent.call(SetDaemonSettings(idle_timeout=5.0)).idle_timeout == 5.0
    raise_own = SetDaemonSettings(agents={Rights.SET: Decision.ALLOW})
    assert refused(lambda: agent.call(raise_own)).code == ErrorCode.DENIED


def test_a_set_beyond_the_limits_is_refused_before_a_person_is_asked(
    lab, lab_as, window
):
    profile = copy.deepcopy(lab.call(GetStation()).profile)
    profile["safety"] = {"limits": LIMITS}
    lab.call(UpdateStation(profile=profile))
    thread, done = calling(lab_as(AGENT), bias("6mV"))
    thread.join(2)
    asked_meanwhile = window.waiting()
    for approval in asked_meanwhile:  # the old way: asked, refused only after
        window.lab.call(AnswerApproval(id=approval.id, allowed=False))
    thread.join(5)
    assert not asked_meanwhile
    assert done["error"].code == ErrorCode.OUT_OF_LIMITS
