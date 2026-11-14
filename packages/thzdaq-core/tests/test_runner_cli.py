import math
import threading
import time
from pathlib import Path

import pytest
from thzdaq_analysis.noise import noise_temperature
from thzdaq_api.measurement_file import CANCELLED, COMPLETED, FAILED, DeviceUse
from thzdaq_core.adapters.json_store import MeasurementStore
from thzdaq_api.measurement_file import read_measurement
from thzdaq_core.domain.errors import ProcedureError, StationError
from thzdaq_core.domain.parameters import FloatParameter
from thzdaq_core.application.runner import MeasurementRunner, RunObserver
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.measurements.catalog import get_procedure, list_procedures
from thzdaq_core.domain.measurements.procedures import IFNoise, IVCurve
from thzdaq_core.domain.station.config import (
    DeviceConfig,
    InstrumentConfig,
    StationConfig,
)
from thzdaq_core.domain.station.station import Station
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
    return Station(config, pause=time.sleep)


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

    def require(
        self, devices, requirements, pause, planned=(), told=None, changed=None
    ):
        return {slot: self.ports[slot] for slot in requirements}

    def device_use(self, ref):
        return DeviceUse(ref)

    def quantities(self, ref):

        return []

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
        saved = read_measurement(dataset.metadata["path"])
        assert saved.status == COMPLETED and saved.records("iv") == dataset.records(
            "iv"
        )
        assert saved.parameters["voltage"] == {"start": 0.0, "stop": 5e-3, "points": 11}

    def test_a_run_sets_back_every_device_it_changed(self, tmp_path):
        from thzdaq_core.adapters.yaml_profiles import load_station
        from thzdaq_core.domain.measurements.procedures import (
            Demagnetize,
            GridCurrentAngle,
            PowerIF,
        )

        with Station(load_station(EXAMPLE), pause=time.sleep, simulate=True) as station:
            yig = station["yig_filter_1:yig_1"]
            yig.tune(7e9)
            before = yig.get_frequency()
            runner = MeasurementRunner(station, MeasurementStore(tmp_path))
            done = runner.run(
                PowerIF(frequency=(4e9, 6e9, 3), point_delay=0),
                devices={
                    "if_filter": "yig_filter_1:yig_1",
                    "detector": "power_meter_1",
                },
            )
            assert done.status == COMPLETED
            assert done.records("power")[-1]["frequency_set"] == 6e9
            assert yig.get_frequency() == pytest.approx(before)
            # a grid and the bias it reads with
            grid, sis1 = station["grid_1"], station["sis_bias_1"]
            grid.rotate_to(15.0)
            sis1.set_voltage(1e-3)
            turned = runner.run(
                GridCurrentAngle(angle=(0, 90, 4), grid_speed=1e6, settle_time=0),
                devices={"grid": "grid_1", "bias": "sis_bias_1"},
            )
            assert turned.status == COMPLETED
            assert grid.get_angle() == pytest.approx(15.0)
            assert sis1.get_voltage() == pytest.approx(1e-3)
            # what a run is for is left as it ends: the coil at the centre
            coil = station["sis_coil_1"]
            coil.set_current(2e-3)
            demagnetized = runner.run(
                Demagnetize(minimum=-3e-3, maximum=3e-3, step=1e-3, step_delay=0),
                devices={"coil": "sis_coil_1"},
            )
            last = demagnetized.records("coil")[-1]["current"]
            assert coil.get_current() == pytest.approx(last) != pytest.approx(2e-3)

    def test_cancel_runs_cleanup_and_marks_dataset(self, tmp_path):
        station = sis_station()
        recorder = Recorder(cancel_at=3)
        runner = MeasurementRunner(station, MeasurementStore(tmp_path), [recorder])
        recorder.runner = runner
        procedure = IVCurve(voltage=(0, 5e-3, 50), settle_time=0, first_point_delay=0)
        dataset = runner.run(procedure, devices={"bias": "sis_bias_1"})
        assert dataset.status == CANCELLED and len(dataset.records("iv")) == 3
        assert station["sis_bias_1"].get_voltage() == 0.0
        assert read_measurement(dataset.metadata["path"]).status == CANCELLED

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
            def require(
                self, devices, requirements, pause, planned=(), told=None, changed=None
            ):
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
        saved = read_measurement(dataset.metadata["path"])
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
        assert {"sis.current_vs_voltage", "if.noise_temperature_vs_frequency"} <= set(
            names
        )
        assert get_procedure("sis.current_vs_voltage") is IVCurve
        with pytest.raises(ProcedureError):
            get_procedure("nope")


def test_parameter_names_cannot_shadow_procedure_api():
    from thzdaq_core.domain.parameters import FloatParameter as F

    with pytest.raises(ProcedureError, match="clash"):

        class Bad(Procedure):
            name = "bad"
            parameters = F("oops", default=1.0)
