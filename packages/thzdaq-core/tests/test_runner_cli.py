import math
import threading
import time
from pathlib import Path

import pytest
from thzdaq_core.analysis.noise import noise_temperature
from thzdaq_core.cli import main
from thzdaq_core.data import (
    CANCELLED,
    COMPLETED,
    FAILED,
    DeviceUse,
    MeasurementStore,
    read_json,
)
from thzdaq_core.errors import ProcedureError, StationError
from thzdaq_core.measurements import (
    FloatParameter,
    MeasurementRunner,
    Procedure,
    RunObserver,
    get_procedure,
    list_procedures,
)
from thzdaq_core.measurements.procedures import IFNoise, IVCurve
from thzdaq_core.station import DeviceConfig, InstrumentConfig, Station, StationConfig
from thzdaq_instruments.capabilities import Switchable
from thzdaq_instruments.sim import SimChopper, SimPowerMeter, SimYigFilter

EXAMPLE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"


def sis_station() -> Station:
    config = StationConfig(
        "bench",
        instruments={
            "sis": InstrumentConfig(
                "sim.sis_block",
                devices={"sis_bias_1": DeviceConfig("sis_bias", channel="DEV4")},
            )
        },
    )
    return Station(config)


class Recorder(RunObserver):
    def __init__(self, cancel_at=None, runner=None):
        self.events = []
        self.cancel_at = cancel_at
        self.runner = runner

    def on_started(self, dataset):
        self.events.append("started")

    def on_record(self, stream, record):
        self.events.append(stream)

    def on_progress(self, done, total):
        if self.cancel_at is not None and done == self.cancel_at:
            self.runner.cancel()

    def on_finished(self, dataset):
        self.events.append(f"finished:{dataset.status}")


class CoupledStation:
    """Simulated detector that sees the chopper load: hot -30 dBm, cold -32 dBm."""

    def __init__(self):
        self.chopper = SimChopper()
        self.ports = {
            "detector": SimPowerMeter(
                model=lambda: -30.0 if self.chopper.position == "hot" else -32.0
            ),
            "if_filter": SimYigFilter().channel("yig_1"),
            "load": self.chopper,
        }

    def require(self, devices, requirements):
        return {slot: self.ports[slot] for slot in requirements}

    def device_use(self, ref):
        return DeviceUse(ref)

    def snapshot(self, refs=None):
        return {"station": {"name": "coupled"}}


class TestRunner:
    def test_iv_curve_records_restores_and_saves(self, tmp_path):
        station = sis_station()
        bias = station["sis_bias_1"]
        bias.set_voltage(1e-3)
        recorder = Recorder()
        runner = MeasurementRunner(station, MeasurementStore(tmp_path), [recorder])
        procedure = IVCurve(voltage=(0, 5e-3, 11), settle_time=0, first_point_delay=0)
        dataset = runner.run(procedure, devices={"bias": "sis_bias_1"})

        assert dataset.status == COMPLETED
        assert len(dataset.records("iv")) == 11
        assert bias.get_voltage() == 1e-3  # restored by on_exit
        assert (
            recorder.events[0] == "started"
            and recorder.events[-1] == "finished:completed"
        )
        assert dataset.devices["bias"].ref == "sis_bias_1"
        assert dataset.devices["bias"].kind == "sis_bias"
        assert dataset.station["identities"] == {"sis": "THZDAQ,SimSisBlock,0,1.0"}
        saved = read_json(dataset.metadata["path"])
        assert saved.status == COMPLETED and saved.records("iv") == dataset.records(
            "iv"
        )
        assert saved.parameters["voltage"] == {"start": 0.0, "stop": 5e-3, "points": 11}

    def test_cancel_runs_cleanup_and_marks_dataset(self, tmp_path):
        station = sis_station()
        recorder = Recorder(cancel_at=3)
        runner = MeasurementRunner(station, MeasurementStore(tmp_path), [recorder])
        recorder.runner = runner
        procedure = IVCurve(voltage=(0, 5e-3, 50), settle_time=0, first_point_delay=0)
        dataset = runner.run(procedure, devices={"bias": "sis_bias_1"})
        assert dataset.status == CANCELLED and len(dataset.records("iv")) == 3
        assert station["sis_bias_1"].get_voltage() == 0.0
        assert read_json(dataset.metadata["path"]).status == CANCELLED

    def test_failure_is_recorded_and_cleanup_still_runs(self, tmp_path):
        cleaned = []

        class Broken(Procedure):
            name = "broken"
            requires = {"bias": Switchable}

            def run(self, ctx):
                ctx.on_exit(lambda: cleaned.append("first"))
                ctx.on_exit(lambda: 1 / 0)
                ctx.record("x", value=1)
                raise RuntimeError("detector exploded")

        class AnyStation(CoupledStation):
            def require(self, devices, requirements):
                return {"bias": SimChopper()}

        class BadObserver(RunObserver):
            def on_record(self, stream, record):
                raise ValueError("plot crashed")

        runner = MeasurementRunner(
            AnyStation(), MeasurementStore(tmp_path), [BadObserver()]
        )
        dataset = runner.run(Broken())
        assert dataset.status == FAILED and "detector exploded" in dataset.error
        assert cleaned == ["first"]
        assert dataset.metadata["cleanup_errors"] == ["cleanup: division by zero"]
        saved = read_json(dataset.metadata["path"])
        assert saved.status == FAILED and "traceback" in saved.metadata

    def test_missing_device_fails_before_any_file(self, tmp_path):
        runner = MeasurementRunner(sis_station(), MeasurementStore(tmp_path))
        with pytest.raises(StationError, match="no device 'bias'"):
            runner.run(IVCurve())
        with pytest.raises(ProcedureError, match="no slots"):
            runner.run(IVCurve(), devices={"detector": "sis_bias_1"})
        assert list(tmp_path.rglob("*.json")) == []

    def test_if_noise_on_coupled_simulators(self):
        runner = MeasurementRunner(CoupledStation())
        dataset = runner.run(
            IFNoise(frequency=(4e9, 5e9, 3), load_delay=0, point_delay=0)
        )
        noise = dataset.records("noise")
        assert len(dataset.records("power")) == 6 and len(noise) == 3
        assert noise[0]["y_factor"] == pytest.approx(2.0)
        assert noise[0]["noise_temperature"] == pytest.approx(
            noise_temperature(-30, -32)
        )
        assert dataset.records("power")[0]["frequency"] == pytest.approx(4e9, abs=2.5e6)

    def test_sleep_wakes_up_on_cancel(self):
        class Slow(Procedure):
            name = "slow"
            requires = {}
            wait = FloatParameter("Wait", default=30.0)

            def run(self, ctx):
                ctx.sleep(self.wait)

        runner = MeasurementRunner(CoupledStation())
        result = {}
        thread = threading.Thread(target=lambda: result.update(d=runner.run(Slow())))
        thread.start()
        time.sleep(0.1)
        assert runner.running
        with pytest.raises(RuntimeError):
            runner.run(Slow())
        started = time.monotonic()
        runner.cancel()
        thread.join(timeout=2)
        assert time.monotonic() - started < 1
        assert result["d"].status == CANCELLED

    def test_parameter_check(self):
        with pytest.raises(ProcedureError, match="warmer"):
            MeasurementRunner(CoupledStation()).run(IFNoise(t_hot=50, t_cold=77))

    def test_noise_temperature_without_contrast_is_nan(self):
        assert math.isnan(noise_temperature(-30, -30))

    def test_registry(self):
        names = [cls.name for cls in list_procedures()]
        assert {"sis.iv_curve", "if.hot_cold"} <= set(names)
        assert get_procedure("sis.iv_curve") is IVCurve
        with pytest.raises(ProcedureError):
            get_procedure("nope")


class TestCli:
    def test_list_and_describe(self, capsys):
        assert main(["list"]) == 0
        assert "sis.iv_curve" in capsys.readouterr().out
        assert main(["describe", "sis.iv_curve"]) == 0
        out = capsys.readouterr().out
        assert "0..7 mV, 351 points" in out and "start:stop:points in mV" in out

    def test_run_simulated_on_example_station(self, tmp_path, capsys):
        code = main(
            [
                "run",
                "sis.iv_curve",
                "--station",
                str(EXAMPLE),
                "--simulate",
                "--device",
                "bias=sis_bias_2",
                "--set",
                "voltage=0:6:13",
                "--set",
                "first_point_delay=0",
                "--set",
                "settle_time=0",
                "--data",
                str(tmp_path),
                "--quiet",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0 and "completed sis.iv_curve [iv: 13]" in out
        path = next(tmp_path.rglob("*.json"))
        assert main(["show", str(path)]) == 0
        assert "voltage" in capsys.readouterr().out

    def test_bad_arguments(self, capsys):
        assert (
            main(["run", "sis.iv_curve", "--station", str(EXAMPLE), "--set", "nope=1"])
            == 2
        )
        assert "--set 'nope=1'" in capsys.readouterr().err
        assert main(["describe", "unknown"]) == 2


def test_parameter_names_cannot_shadow_procedure_api():
    from thzdaq_core.measurements import FloatParameter as F

    with pytest.raises(ProcedureError, match="clash"):

        class Bad(Procedure):
            name = "bad"
            parameters = F("oops", default=1.0)
