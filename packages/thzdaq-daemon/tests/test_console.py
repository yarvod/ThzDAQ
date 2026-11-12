"""A console of a window, end to end: its kernel (ipykernel, as the window
starts it) opens on the daemon as console, and a measurement it runs is
restored when the kernel restarts or ends, as a script's is."""

import os

import pytest
from lab_helpers import wait_for
from test_process import start
from thzdaq_api import console
from thzdaq_api.devices import ReadDevice
from thzdaq_api.measurements import ListRuns

pytest.importorskip("ipykernel", reason="the console's kernel runs where ipykernel is")
from jupyter_client import KernelManager  # noqa: E402
from jupyter_client.kernelspec import KernelSpec  # noqa: E402
from thzdaq_gui.kernel import NAME, GivenSpec  # noqa: E402

LOOK = """\
bias = lab["sis_bias_1"]
with lab.measurement("look", devices=[bias]) as m:
    m.restore(bias, "voltage_set")
    bias.voltage_set = "2mV"
    print("set", flush=True)
    while True:
        m.sleep(0.1)
"""


def ran(client, code, until=None, timeout=60):
    """What the code printed (up to a line holding until, when given)."""
    sent = client.execute(code)
    printed = ""
    while True:
        message = client.get_iopub_msg(timeout=timeout)
        if message["parent_header"].get("msg_id") != sent:
            continue
        content = message["content"]
        if message["msg_type"] == "stream":
            printed += content["text"]
            if until is not None and until in printed:
                return printed
        elif message["msg_type"] == "error":
            raise AssertionError("\n".join(content["traceback"]))
        elif message["msg_type"] == "status" and content["execution_state"] == "idle":
            return printed


@pytest.fixture
def kernel(home, tmp_path):
    spec = KernelSpec(argv=console.kernel_command(), language="python")
    manager = KernelManager(kernel_spec_manager=GivenSpec(spec=spec), kernel_name=NAME)
    environment = {
        **os.environ,
        **console.kernel_environment(True, tmp_path),
        console.IPYTHON_DIR_ENV: str(tmp_path / "ipython"),
    }
    manager.start_kernel(env=environment, cwd=str(tmp_path))
    client = manager.client()
    client.start_channels()
    try:
        client.wait_for_ready(timeout=60)
    except RuntimeError as e:
        manager.shutdown_kernel(now=True)
        pytest.skip(f"no kernel starts here: {e}")
    yield manager, client
    client.stop_channels()
    if manager.has_kernel:
        manager.shutdown_kernel(now=True)


def voltage_set(lab):
    return lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set",))).values[
        "voltage_set"
    ]


def looked(lab):
    return [run for run in lab.call(ListRuns()) if run.title == "look"]


def test_a_console_opens_on_the_daemon_as_console(home, kernel):
    lab = start(home)
    _, client = kernel
    ran(client, console.OPENING)
    assert ran(client, "print(lab.origin, lab['sis_bias_1'].voltage_set)") == (
        "console 0.0 V\n"
    )
    ran(client, 'lab["sis_bias_1"].voltage_set = "1mV"')  # within: no question
    assert voltage_set(lab) == pytest.approx(1e-3)


@pytest.mark.parametrize("end", ["restart", "shutdown"])
def test_its_measurement_is_restored_when_the_kernel_goes(home, kernel, end):
    lab = start(home)
    manager, client = kernel
    ran(client, console.OPENING)
    ran(client, 'lab["sis_bias_1"].voltage_set = "1mV"')
    ran(client, LOOK, until="set")
    assert voltage_set(lab) == pytest.approx(2e-3)
    # jupyter_client interrupts what runs first: the with block ends its session
    getattr(manager, f"{end}_kernel")()
    wait_for(lambda: looked(lab)[0].status != "running", timeout=15)
    assert looked(lab)[0].status == "interrupted"
    assert voltage_set(lab) == pytest.approx(1e-3)
