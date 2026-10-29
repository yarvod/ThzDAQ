"""thzdaq on the daemon's use cases: what people type and what they read."""

import json
import os
import subprocess
import sys

from thzdaq_api.measurements import CancelMeasurement, StartMeasurement

FAST = ["--set", "settle_time=0", "--set", "first_point_delay=0"]
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


def test_the_daemon_is_asked_about_itself(thzdaq):
    code, out, _ = thzdaq("daemon", "status")
    assert code == 0 and "daemon (simulator)" in out and "profile 2sb" in out
    code, out, _ = thzdaq("daemon", "settings", "--idle-timeout", "0")
    assert out.strip() == "idle timeout: never"
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
