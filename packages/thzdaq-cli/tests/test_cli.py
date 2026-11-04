"""thzdaq on the daemon's use cases: what people type and what they read."""

import json
import os
import subprocess
import sys
import time

import pytest
from thzdaq_api.devices import SetQuantity
from thzdaq_api.measurements import CancelMeasurement, StartMeasurement

AGENT = "mcp:claude"

FAST = ["--set", "settle_time=0", "--set", "first_point_delay=0"]


def bias(value):
    return SetQuantity(ref="sis_bias_1", key="voltage_set", value=value)


SLOW_IV = {
    "voltage": {"start": 0.0, "stop": 5e-3, "points": 2000},
    "settle_time": 0.01,
    "first_point_delay": 0.0,
}


def test_devices_are_read_and_set_with_units(thzdaq):
    code, out, _ = thzdaq("devices")
    assert code == 0 and "sis_bias_1" in out and "sis_bias" in out
    code, out, _ = thzdaq("set", "sis_bias_1", "voltage_set", "2.3mV")
    assert code == 0 and out.strip() == "sis_bias_1 voltage_set = 0.0023 V"
    code, out, _ = thzdaq("--json", "read", "sis_bias_1", "voltage_set")
    assert json.loads(out)["values"]["voltage_set"] == 0.0023
    code, out, _ = thzdaq("device", "sis_bias_1")
    assert "voltage_set" in out and "setting offset_voltage" in out


def test_a_dangerous_set_is_asked_and_refused_without_a_terminal(thzdaq):
    code, _, err = thzdaq("set", "sis_bias_1", "active", "off")
    assert code == 1 and "not asked without a terminal" in err
    code, out, _ = thzdaq("--yes", "set", "sis_bias_1", "active", "off")
    assert code == 0 and "active = off" in out


def test_procedures_are_described_as_they_are_typed(thzdaq):
    code, out, _ = thzdaq("procedures")
    assert code == 0 and "sis.iv_curve" in out
    code, out, _ = thzdaq("describe", "sis.iv_curve", "--set", "voltage=0:2:11")
    assert code == 0 and "11 steps" in out and "0:7:351" in out and "mV" in out


def test_a_run_is_followed_to_its_file(thzdaq, tmp_path):
    code, out, err = thzdaq(
        "run", "sis.iv_curve", "--device", "bias=sis_bias_2",
        "--set", "voltage=0:2:5", *FAST, "--workspace", str(tmp_path),
    )  # fmt: skip
    assert code == 0, err
    assert "completed (5/5 steps)" in out and str(tmp_path / "data") in out
    path = out.strip().splitlines()[-1].removeprefix("file ")
    code, out, _ = thzdaq("show", path)
    assert code == 0 and "iv     5" in out
    code, out, _ = thzdaq("measurements")
    assert "completed" in out and "cli" in out
    code, out, _ = thzdaq("status")
    assert out.strip() == "no measurement runs"


def test_a_slot_takes_the_one_device_that_suits_or_asks(thzdaq):
    code, _, err = thzdaq("run", "sis.iv_curve", "--set", "voltage=0:2:5", *FAST)
    assert code == 2 and "one of sis_bias_1, sis_bias_2" in err
    code, out, err = thzdaq(
        "run", "if.hot_cold", "--set", "frequency=4:4:1", "--dry-run",
        "--device", "load=chopper_1", "--device", "if_filter=yig_filter_1:yig_1",
    )  # fmt: skip
    assert code == 0 and "planned" in out
    assert "detector: power_meter_1" in err  # the one that suits


def test_a_conflict_is_asked_and_shared_with_yes(thzdaq, lab):
    other = lab.call(
        StartMeasurement(
            procedure="sis.iv_curve", parameters=SLOW_IV, devices={"bias": "sis_bias_1"}
        )
    )
    given = ["--device", "bias=sis_bias_1", "--set", "voltage=0:2:5", *FAST]
    code, _, err = thzdaq("run", "sis.iv_curve", *given)
    assert code == 1 and f"#{other.id}" in err and "--yes" in err
    code, out, err = thzdaq("--yes", "run", "sis.iv_curve", *given)
    assert code == 0, err
    assert "completed" in out
    code, out, _ = thzdaq("cancel", str(other.id))
    assert code == 0 and f"#{other.id}" in out
    lab.call(CancelMeasurement(id=other.id))


def test_watch_tells_how_an_ended_run_went(thzdaq):
    code, *_ = thzdaq(
        "run", "sis.iv_curve", "--device", "bias=sis_bias_1",
        "--set", "voltage=0:1:3", *FAST,
    )  # fmt: skip
    code, out, _ = thzdaq("watch", "1")
    assert code == 0 and "#1 SIS I-V curve: completed" in out
    code, out, _ = thzdaq("watch", "99")
    assert code == 1 and "no measurement #99" in out


def test_plot_opens_a_measurements_plots_in_a_window(thzdaq, tmp_path, monkeypatch):
    from thzdaq_api import host

    opened = []
    monkeypatch.setattr(host, "window_command", lambda: ["ThzDAQ"])
    monkeypatch.setattr(host, "start_apart", opened.append)
    code, out, err = thzdaq(
        "run", "sis.iv_curve", "--device", "bias=sis_bias_1",
        "--set", "voltage=0:1:3", *FAST,
    )  # fmt: skip
    path = out.strip().splitlines()[-1].removeprefix("file ")
    code, out, err = thzdaq("--simulate", "plot", "1")
    assert code == 0, err
    assert out.strip() == "the plots of #1 open in a window"
    code, out, err = thzdaq(
        "plot", path, "--table", "iv", "--x", "voltage", "--y", "current"
    )
    assert code == 0, err
    assert opened == [
        ["ThzDAQ", "--plot", "1", "--simulate"],
        ["ThzDAQ", "--plot", path, "--table", "iv", "--x", "voltage",
         "--y", "current"],
    ]  # fmt: skip
    code, _, err = thzdaq("plot", "99")
    assert code == 1 and "99" in err
    code, _, err = thzdaq("plot", "1", "--table", "iv")
    assert code == 1 and "table, x and y" in err
    code, _, err = thzdaq("plot", str(tmp_path / "missing.json"))
    assert code == 1 and len(opened) == 2


def test_the_daemon_is_asked_about_itself(thzdaq):
    code, out, _ = thzdaq("daemon", "status")
    assert code == 0 and "daemon (simulator)" in out and "profile 2sb" in out
    code, out, _ = thzdaq("daemon", "settings", "--idle-timeout", "0")
    assert out.splitlines()[0] == "idle timeout: never"
    code, out, _ = thzdaq("--yes", "daemon", "reset-lane", "sis_block_1")
    assert code == 0
    code, out, _ = thzdaq("station", "show")
    assert "sis_block_1" in out and "sis_bias_1: SIS1 (sis_bias)" in out
    code, out, _ = thzdaq("--yes", "safe")
    assert code == 0 and "no safe state" in out


def test_the_command_starts_the_daemon_it_needs(tmp_path):
    """No daemon runs: status says so (exit 3); another command starts the
    simulator's daemon and says it did; stop ends it."""
    env = {**os.environ, "THZDAQ_DAEMON_DIR": str(tmp_path / "daemon")}

    def thzdaq(*argv):
        return subprocess.run(
            [sys.executable, "-m", "thzdaq_cli", "--simulate", *argv],
            capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
        )  # fmt: skip

    try:
        assert thzdaq("daemon", "status").returncode == 3
        done = thzdaq("--json", "devices")
        assert done.returncode == 0 and "daemon started" in done.stderr
        assert json.loads(done.stdout) == []  # it works with no profile
        assert thzdaq("daemon", "stop").returncode == 0
    finally:
        thzdaq("daemon", "kill")


def test_a_command_in_an_agents_shell_waits_for_a_person(thzdaq, lab, monkeypatch):
    """Claude Code runs thzdaq in its shell: --yes does not stand for a person."""
    from thzdaq_api.origins import AGENT_CLI, CLI
    from thzdaq_cli.client import origin

    assert origin() == CLI
    monkeypatch.setenv("CLAUDECODE", "1")
    assert origin() == AGENT_CLI
    lab.origin = origin()
    code, _, err = thzdaq("--yes", "set", "sis_bias_1", "voltage_set", "1mV")
    assert code == 1 and "window" in err


def test_people_set_what_agents_may_do(thzdaq):
    code, out, _ = thzdaq("daemon", "settings")
    assert "set      ask" in out and "station  deny" in out and "(always)" in out
    code, out, _ = thzdaq("daemon", "settings", "--agents", "set=allow")
    assert code == 0 and "set      allow" in out and "idle timeout" in out
    code, _, err = thzdaq("daemon", "settings", "--agents", "answer=allow")
    assert code == 1 and "stay deny" in err
    code, _, err = thzdaq("daemon", "settings", "--agents", "set=maybe")
    assert code == 2 and "set=maybe" in err


def agent_asks(lab, operation):
    """An agent's call in a thread: it waits for a person (a window here)."""
    import threading

    from thzdaq_api.errors import LabError
    from thzdaq_core.application.local import LocalLab

    done = {}

    def call():
        try:
            done["result"] = LocalLab(lab.assembled, AGENT).call(operation)
        except LabError as e:
            done["error"] = e

    thread = threading.Thread(target=call)
    thread.start()
    return thread, done


@pytest.fixture
def window(lab):
    """A person's window listens: what agents change waits for an answer."""
    from thzdaq_api.origins import GUI
    from thzdaq_core.application.local import LocalLab

    stop = LocalLab(lab.assembled, GUI, GUI).subscribe(lambda event: None)
    yield
    stop()


def waiting(lab, count):
    from thzdaq_api.approvals import ListApprovals

    deadline = time.monotonic() + 5
    while len(lab.call(ListApprovals())) < count:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    return lab.call(ListApprovals())


def test_what_waits_is_listed_and_answered(thzdaq, lab, window):
    code, out, _ = thzdaq("approvals")
    assert code == 0 and out.strip() == "nothing waits"
    thread, done = agent_asks(lab, bias("2mV"))
    (approval,) = waiting(lab, 1)
    code, out, _ = thzdaq("approvals")
    assert f"#{approval.id} {AGENT}: sis_bias_1" in out and "2 mV" in out
    code, out, _ = thzdaq(
        "approvals", "answer", str(approval.id), "--allow", "--value", "1.5 mV"
    )
    thread.join(5)
    assert code == 0 and done["result"].value == pytest.approx(1.5e-3)
    thread, done = agent_asks(lab, bias("3mV"))
    (approval,) = waiting(lab, 1)
    thzdaq("approvals", "answer", str(approval.id), "--deny", "--text", "too high")
    thread.join(5)
    assert "too high" in done["error"].message


def test_an_agents_shell_does_not_answer(thzdaq, lab, window, monkeypatch):
    from thzdaq_api.approvals import AnswerApproval
    from thzdaq_api.origins import AGENT_CLI

    thread, done = agent_asks(lab, bias("2mV"))
    (approval,) = waiting(lab, 1)
    monkeypatch.setenv("CLAUDECODE", "1")
    lab.origin = AGENT_CLI
    code, _, err = thzdaq("approvals", "answer", str(approval.id), "--allow")
    assert code == 1 and "not for cli:agent" in err
    code, _, err = thzdaq("approvals", "watch")
    assert code == 1 and "agent's shell" in err
    lab.origin = "cli"
    lab.call(AnswerApproval(id=approval.id, allowed=False))
    thread.join(5)


def test_watch_asks_only_in_a_terminal(thzdaq):
    code, _, err = thzdaq("approvals", "watch")
    assert code == 1 and "terminal" in err


def test_watch_asks_the_person_at_the_terminal(thzdaq, lab, window, monkeypatch):
    """Each one as the window's dialog asks it: another value, the device
    typed for a dangerous step, words, a question's choice; Ctrl+C ends."""
    from thzdaq_api.approvals import AnswerApproval, AskUser, WaitAnswer
    from thzdaq_api.origins import ANSWERING_CLI
    from thzdaq_core.application.local import LocalLab

    set_bias, set_to = agent_asks(lab, bias("2mV"))
    waiting(lab, 1)
    switch_off, switched = agent_asks(
        lab, SetQuantity(ref="sis_bias_1", key="active", value=False)
    )
    waiting(lab, 2)
    agent = LocalLab(lab.assembled, AGENT)
    question = agent.call(
        AskUser(question="Cooled down?", options=("yes", "no"), timeout=0)
    )
    last = agent.call(AskUser(question="Anything else?", timeout=0))
    typed = iter(
        ["y", "1.5 mV", "",  # another value
         "y", "", "sis_bias", "", "y", "", "sis_bias_1", "careful",  # mistyped
         "1", "at 4.2 K"]  # the choice and words
    )  # fmt: skip
    kinds = []

    def person(prompt=""):
        kinds.append({c.kind for c in lab.assembled.control.clients()})
        try:
            return next(typed)
        except StopIteration:
            raise KeyboardInterrupt from None

    monkeypatch.setattr("builtins.input", person)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    code, out, err = thzdaq("approvals", "watch")
    assert code == 0 and ANSWERING_CLI in kinds[0]
    assert "Type sis_bias_1 to allow this" in err and "): again" in err
    assert "Cooled down?" in out and "Anything else?" in out
    set_bias.join(5)
    switch_off.join(5)
    assert set_to["result"].value == pytest.approx(1.5e-3)
    assert switched["result"].value is False
    answered = agent.call(WaitAnswer(id=question.id, timeout=1)).answer
    assert (answered.choice, answered.text, answered.by) == ("yes", "at 4.2 K", "cli")
    lab.call(AnswerApproval(id=last.id, allowed=False))


def test_agent_setup_writes_what_agents_read_in_a_folder(thzdaq, tmp_path):
    import tomllib

    from thzdaq_api import guides

    folder = tmp_path / "experiment"
    code, out, err = thzdaq("--simulate", "agent-setup", str(folder))
    assert code == 0, err
    started = [sys.executable, "-m", "thzdaq_cli"]  # this Python: not a thzdaq script
    args = ["--simulate", "mcp", "--workspace", str(folder)]
    claude = json.loads((folder / ".mcp.json").read_text())
    assert claude["mcpServers"]["thzdaq"] == {
        "command": started[0],
        "args": started[1:] + args,
    }
    codex = tomllib.loads((folder / ".codex" / "config.toml").read_text())
    assert codex["mcp_servers"]["thzdaq"]["args"] == started[1:] + args
    assert codex["mcp_servers"]["thzdaq"]["tool_timeout_sec"] >= 60
    assert (folder / "AGENTS.md").read_text() == guides.guide(guides.AGENTS)
    assert (folder / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert "written .mcp.json" in out and " ".join(started + args) in out
    # A workspace: what the agent runs there with thzdaq measures there too
    assert "written thzdaq.toml" in out and (folder / "thzdaq.toml").exists()


def test_agent_setup_keeps_what_a_person_wrote(thzdaq, tmp_path, monkeypatch):
    """Their servers, their guide and their notes stay; ours is added. The
    command named is the thzdaq that runs, from any folder."""
    script = tmp_path / "bin" / "thzdaq"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    monkeypatch.setattr(sys, "argv", [str(script)])
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {"other": {"command": "x"}}}')
    (tmp_path / "AGENTS.md").write_text("our rules\n")
    (tmp_path / "CLAUDE.md").write_text("notes\n")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text('model = "o4"\n')
    code, out, _ = thzdaq("agent-setup")
    assert code == 0
    servers = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]
    assert set(servers) == {"other", "thzdaq"}
    assert servers["thzdaq"]["command"] == str(script)
    assert (tmp_path / "AGENTS.md").read_text() == "our rules\n"
    assert (tmp_path / "CLAUDE.md").read_text() == "notes\n\n@AGENTS.md\n"
    codex = (tmp_path / ".codex" / "config.toml").read_text()
    assert codex.startswith('model = "o4"\n') and "[mcp_servers.thzdaq]" in codex
    code, out, _ = thzdaq("agent-setup")  # again: nothing twice
    assert "kept .codex/config.toml" in out and "kept CLAUDE.md" in out
    assert (tmp_path / ".codex" / "config.toml").read_text() == codex
    code, out, _ = thzdaq("agent-setup", "--force")
    assert (
        "written AGENTS.md" in out
        and "our rules" not in (tmp_path / "AGENTS.md").read_text()
    )


def test_mcp_is_served_by_its_package_or_says_what_to_install(thzdaq, monkeypatch):
    from thzdaq_cli import agents
    from thzdaq_mcp.server import serve

    (found,) = agents.entry_points(group=agents.PLUGINS, name=agents.MCP)
    assert found.load() is serve
    monkeypatch.setattr(agents, "entry_points", lambda **_: ())
    code, _, err = thzdaq("mcp")
    assert code == 1 and "thzdaq[mcp]" in err


def test_a_file_is_run_as_python_runs_it(thzdaq, tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", list(sys.argv))
    monkeypatch.setattr(sys, "path", list(sys.path))
    file = tmp_path / "args.py"
    file.write_text(
        "import sys\nfrom pathlib import Path\n"
        "print(__name__, sys.argv[1:], Path(sys.path[0]).name)\n"
    )
    code, out, _ = thzdaq("run-script", str(file), "--", "a", "-b")
    assert code == 0 and out == f"__main__ ['a', '-b'] {tmp_path.name}\n"


def test_a_script_is_started_with_what_it_may_do(thzdaq, lab, tmp_path):
    from thzdaq_api.scripts import ListScripts

    file = tmp_path / "quiet.py"
    file.write_text("print('quiet')\n")
    code, _, err = thzdaq("script", "start", str(file), "--allow", "sweep:sis_bias_1")
    assert code == 2 and "set:" in err
    code, out, _ = thzdaq(
        "script",
        "start",
        str(file),
        "--allow",
        "set:sis_bias_1",
        "--share",
        "sis_bias_1",
    )
    assert code == 0 and "may set:sis_bias_1" in out
    (started,) = lab.call(ListScripts())
    assert started.share == ("sis_bias_1",) and started.workspace == str(tmp_path)
