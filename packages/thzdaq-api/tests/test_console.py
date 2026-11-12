"""A console of the window as its kernel sees it: how it starts, what its
environment says, who it calls the daemon as, what it completes."""

import sys
from pathlib import Path

import pytest
from thzdaq_api import console, host
from thzdaq_api.devices import (
    ActionInfo,
    ArgumentInfo,
    DescribeDevice,
    DeviceDescription,
    DeviceInfo,
    ListDevices,
    Prefix,
    QuantityInfo,
)
from thzdaq_api.lab import Bench, caller
from thzdaq_api.measurements import ListProcedures, ProcedureSummary
from thzdaq_api.origins import AGENT_SHELLS, CONSOLE, CONSOLE_CLIENT, CONSOLE_ENV
from thzdaq_api.scripts import SCRIPT_ID_ENV

MILLI = Prefix("m", 1e-3, "×10⁻³")
BIAS = DeviceInfo("sis_bias_1", "SIS1", "block", "scontel", "sis_bias", "sis_bias", ())
DESCRIBED = DeviceDescription(
    BIAS,
    (
        QuantityInfo("voltage", "Voltage", "V", prefixes=(MILLI,)),
        QuantityInfo(
            "voltage_set", "Voltage set", "V", settable=True,
            minimum=-0.03, maximum=0.03, prefixes=(MILLI,),
        ),
    ),
    (ActionInfo("sweep", "Sweep", (ArgumentInfo("points", "Points", kind="int"),)),),
)  # fmt: skip
PROCEDURES = (
    ProcedureSummary("sis.current_vs_voltage", "SIS I-V", ""),
    ProcedureSummary("if.power_vs_frequency", "IF P-f", ""),
)


class FakeLab:
    """A daemon that knows one device and two procedures."""

    origin = CONSOLE

    def call(self, operation):
        answers = {
            DescribeDevice: DESCRIBED,
            ListDevices: (BIAS,),
            ListProcedures: PROCEDURES,
        }
        return answers[type(operation)]


def test_a_kernel_runs_the_scripts_python(monkeypatch, tmp_path):
    command = console.kernel_command()
    assert command == [sys.executable, "-m", console.KERNEL, "-f", console.CONNECTION]
    monkeypatch.setattr(host, "frozen", lambda: True)
    monkeypatch.setattr(host, "program_dir", lambda: tmp_path)
    built = host.executable(tmp_path, host.CLI_PROGRAM)
    assert console.kernel_command() == [
        str(built), host.RUN_SCRIPT, "-m", console.KERNEL, "--",
        "-f", console.CONNECTION,
    ]  # fmt: skip


def test_a_kernel_works_where_its_window_does(tmp_path):
    found = console.kernel_environment(True, tmp_path)
    assert found[CONSOLE_ENV] == "1" and found["THZDAQ_SIMULATE"] == "1"
    assert found["THZDAQ_WORKSPACE"] == str(tmp_path)
    assert Path(found[console.IPYTHON_DIR_ENV]) == host.user_dir() / "ipython"
    real = console.kernel_environment(False, None)
    assert real["THZDAQ_SIMULATE"] == "0" and "THZDAQ_WORKSPACE" not in real


def test_a_kernel_calls_as_console_with_a_persons_rights(monkeypatch):
    for name in (*AGENT_SHELLS, SCRIPT_ID_ENV, CONSOLE_ENV):
        monkeypatch.delenv(name, raising=False)
    assert caller("scan") == ("script:scan", "script")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert caller("scan") == ("script:agent:scan", "script")
    monkeypatch.setenv(CONSOLE_ENV, "1")  # a person types into it, whatever its shell
    assert caller("scan") == (CONSOLE, CONSOLE_CLIENT)


def test_a_script_runs_in_a_console_as_percent_run(tmp_path):
    code = console.run_file(tmp_path / "my scans" / "pv.py")
    assert code == f'%run "{(tmp_path / "my scans" / "pv.py").as_posix()}"'


def test_ipython_completes_the_refs_of_the_bench():
    assert Bench(FakeLab())._ipython_key_completions_() == ["sis_bias_1"]


class Shell:
    def __init__(self, **names):
        self.user_ns = names


def completed(matcher, text):
    from IPython.core.completer import CompletionContext

    context = CompletionContext(
        full_text=text, cursor_position=len(text), cursor_line=0,
        token=text.rsplit(".", 1)[-1], limit=None,
    )  # fmt: skip
    found = matcher(context)
    return {c.text: c.type for c in found["completions"]}, found.get("matched_fragment")


def test_the_kernel_completes_a_device_with_units_and_limits():
    pytest.importorskip("ipykernel", reason="the kernel runs where ipykernel is")
    from thzdaq_api.kernel import BenchCompletions

    lab = Bench(FakeLab())
    completions = BenchCompletions(Shell(lab=lab, bias=lab["sis_bias_1"], n=3))
    found, typed = completed(completions.device, "bias.vol")
    assert (
        found
        == {
            "voltage": "quantity, V, read only",
            "voltage_set": "quantity, V, -30 mV … 30 mV",
        }
        and typed == "vol"
    )
    found, _ = completed(completions.device, 'x = lab["sis_bias_1"].')
    assert found["sweep"] == "action(points)" and len(found) == 3
    assert completed(completions.device, "n.re")[0] == {}  # not a device


def test_the_kernel_completes_the_names_of_procedures():
    pytest.importorskip("ipykernel", reason="the kernel runs where ipykernel is")
    from thzdaq_api.kernel import BenchCompletions

    completions = BenchCompletions(Shell(lab=Bench(FakeLab())))
    found, typed = completed(completions.procedure, 'run = lab.run("sis.cu')
    assert found == {"sis.current_vs_voltage": "procedure: SIS I-V"}
    assert typed == "sis.cu"
