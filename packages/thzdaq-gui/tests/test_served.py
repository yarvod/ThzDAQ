"""The window on a daemon served in this process over HTTP + SSE, as the program
works with its daemon: what other clients do reaches it through the event
stream, and a client of another process keeps the daemon at the window's exit."""

import subprocess
import sys
import threading
from pathlib import Path

import msgspec
import pytest
from thzdaq_api.devices import SetQuantity
from thzdaq_api.errors import LabError
from thzdaq_api.measurements import StartMeasurement
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE
from thzdaq_api.remote import RemoteLab

# The daemon's tests serve it in a process: Served
sys.path.insert(0, str(Path(__file__).parents[2] / "thzdaq-daemon" / "tests"))

AGENT = "mcp:claude"
# A client of another process: it listens until its input ends
LISTENER = """
import sys

import msgspec
from thzdaq_api.daemon import HostInfo
from thzdaq_api.remote import RemoteLab

host = msgspec.json.decode(sys.argv[1].encode(), type=HostInfo)
RemoteLab(host, "cli", "cli").subscribe(lambda event: None)
sys.stdin.read()
"""


@pytest.fixture
def served(tmp_path):
    from served import Served

    served = Served(tmp_path)
    yield served
    served.close()


@pytest.fixture
def connect(served):
    """The session's labs: RemoteLab to the served daemon."""
    labs = []

    def remote(simulate, origin="gui", kind="gui", window=""):
        labs.append(RemoteLab(served.host, origin, kind, window=window))
        return labs[-1]

    yield remote
    for lab in labs:
        lab.close()


@pytest.fixture
def cli(connect):
    return connect(True, "cli", "cli")


def test_a_set_from_the_cli_shows_in_the_dock(window, cli, wait):
    panel = window.docks["device:sis_bias_1"].widget().panels[0]
    cli.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1.5mV"))
    wait(lambda: panel.fields["voltage_set"].value() == pytest.approx(0.0015))


def test_a_measurement_from_the_cli_is_drawn(window, session, cli, wait):
    run = cli.call(
        StartMeasurement(
            procedure=CURRENT_VS_VOLTAGE,
            parameters={
                "voltage": {"start": 0, "stop": 0.002, "points": 6},
                "settle_time": 0,
                "first_point_delay": 0,
            },
            devices={"bias": "sis_bias_1"},
        )
    )
    wait(lambda: [m.id for m in session.measurements.items] == [run.id])
    wait(lambda: "I-V" in window.hub.graphs)
    graph = window.hub.graph("I-V")
    wait(lambda: sum(len(points) for points in graph.points.values()) == 6)


def test_an_agents_set_is_a_card_in_the_window(window, connect, wait):
    agent = connect(True, AGENT, "mcp")
    done = {}

    def call():
        try:
            done["result"] = agent.call(
                SetQuantity(ref="sis_bias_1", key="voltage_set", value="2mV")
            )
        except LabError as e:
            done["error"] = e

    thread = threading.Thread(target=call)
    thread.start()
    wait(lambda: window.approvalPrompts.current is not None)
    dialog = window.approvalPrompts.current
    assert dialog.approval.origin == AGENT and dialog.value.text() == "2 mV"
    dialog.allow.click()
    thread.join(5)
    assert done["result"].value == pytest.approx(0.002)


def test_a_cli_listening_keeps_the_daemon_at_the_exit(
    window, served, wait, monkeypatch
):
    from PySide6.QtWidgets import QDialog

    offered = []

    def exec_(dialog):  # what the person would see checked; they stay
        offered.append(dialog.stopDaemon.isChecked())
        return QDialog.Rejected

    monkeypatch.setattr("thzdaq_gui.exit_dialog.ExitDialog.exec", exec_)
    assert not window.close() and offered == [True]  # only this window listens
    host = msgspec.json.encode(served.host).decode()
    listener = subprocess.Popen(
        [sys.executable, "-c", LISTENER, host], stdin=subprocess.PIPE
    )
    try:
        wait(lambda: any(c.kind == "cli" for c in served.clients.all()), 15)
        assert not window.close() and offered == [True, False]
    finally:
        listener.communicate(timeout=10)
        window.confirm_exit = False  # the fixture closes it without asking
