import pytest
from thzdaq_core.data import COMPLETED, DeviceUse
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements import MeasurementRunner, StringListParameter
from thzdaq_core.measurements.procedures import Demagnetize, Monitor
from thzdaq_core.measurements.procedures.monitor import read_port, readers_for
from thzdaq_core.sis import (
    CALIBRATION_FIELDS,
    calibration_for,
    default_sis_calibration,
    demagnetization_currents,
    evaluate_numeric_expression,
    evaluate_sis_calibration,
    normalize_sis_calibration,
)
from thzdaq_instruments.sim import (
    SimChopper,
    SimPowerMeter,
    SimSisBlock,
    SimTemperatureController,
)


class TestCalibration:
    def test_expressions(self):
        assert evaluate_numeric_expression(
            "5.4767381740816745e-09 / 5"
        ) == pytest.approx(1.0953e-9, rel=1e-4)
        assert evaluate_numeric_expression("-(2 + 3) * 2 ** 3") == -40
        for bad in ("__import__('os')", "a + 1", "2 ** 1000", "", "1 / 0", "[1]"):
            with pytest.raises(ValueError):
                evaluate_numeric_expression(bad)

    def test_normalize_keeps_expressions_evaluate_computes(self):
        calibration = default_sis_calibration("DEV4")
        assert (
            normalize_sis_calibration(calibration)["CurrentADC"][1]
            == "-0.04757314547896385 / 5"
        )
        assert evaluate_sis_calibration(calibration)["CurrentADC"][1] == pytest.approx(
            -0.04757314547896385 / 5
        )

    def test_validation(self):
        calibration = default_sis_calibration("DEV2")
        missing = dict(calibration)
        missing.pop("VoltageStep")
        with pytest.raises(ValueError, match="Missing"):
            normalize_sis_calibration(missing)
        with pytest.raises(ValueError, match="Unknown"):
            normalize_sis_calibration({**calibration, "Colour": 1})
        with pytest.raises(ValueError, match="array of 2"):
            normalize_sis_calibration({**calibration, "VoltageDac": [1]})
        assert set(calibration) == set(CALIBRATION_FIELDS)

    def test_calibration_for_prefers_stored(self):
        stored = default_sis_calibration("DEV2")
        assert calibration_for("DEV4", stored) == stored
        assert calibration_for("DEV4") == default_sis_calibration("DEV4")


class TestDemagnetization:
    def test_sequence(self):
        currents = demagnetization_currents(-30e-3, 30e-3, 5e-3)
        assert currents[0] == pytest.approx(-30e-3) and currents[-1] == pytest.approx(
            0, abs=1e-12
        )
        jumps = [abs(b - a) for a, b in zip(currents, currents[1:])]
        assert max(jumps) <= 5e-3 + 1e-12
        turning = [
            c
            for a, c, b in zip(currents, currents[1:], currents[2:])
            if (c - a) * (b - c) < 0
        ]
        assert turning == pytest.approx([30e-3, -25e-3, 20e-3, -15e-3, 10e-3, -5e-3])

    def test_invalid_ranges(self):
        with pytest.raises(ValueError):
            demagnetization_currents(1, 0, 0.1)
        with pytest.raises(ValueError):
            demagnetization_currents(0, 1, 0)

    def test_procedure_drives_the_coil(self):
        coil = SimSisBlock().ctrl("DEV3")

        class Bench:
            def device_use(self, ref):
                return DeviceUse(ref)

            def require(self, devices, requirements):
                return {"coil": coil}

            def snapshot(self):
                return {}

        procedure = Demagnetize(minimum=-10e-3, maximum=10e-3, step=5e-3, step_delay=0)
        dataset = MeasurementRunner(Bench()).run(procedure)
        assert dataset.status == COMPLETED
        assert len(dataset.records("coil")) == procedure.estimate_steps()
        assert coil.get_current() == pytest.approx(0, abs=1e-12)
        with pytest.raises(ProcedureError):
            Demagnetize(minimum=1e-3, maximum=-1e-3).validate()


class TestMonitor:
    def test_readers_by_capability(self):
        sis = SimSisBlock().channel("DEV4")
        sis.set_voltage(3e-3)
        assert set(read_port(sis)) == {"voltage", "current"}
        assert read_port(SimPowerMeter(power=-12.0)) == {"power": -12.0}
        assert read_port(SimSisBlock().ctrl("DEV3")) == {"coil_current": 0.0}
        assert readers_for(SimChopper()) == []

    def test_monitor_for_a_duration(self):
        ports = {
            "detector": SimPowerMeter(power=-20.0),
            "cryostat": SimTemperatureController().channel("A"),
        }

        class Bench:
            def device_use(self, ref):
                return DeviceUse(ref)

            def require(self, devices, requirements):
                return {slot: ports[slot] for slot in requirements}

            def snapshot(self):
                return {}

        procedure = Monitor(watch=("detector", "cryostat"), interval=0.02, duration=0.1)
        dataset = MeasurementRunner(Bench()).run(procedure)
        samples = dataset.records("samples")
        assert dataset.status == COMPLETED
        assert {s["device"] for s in samples} == {"detector", "cryostat"}
        assert 4 <= len(samples) // 2 <= 7
        temperatures = Monitor.plots[1].curves(samples)
        assert list(temperatures) == [("cryostat",)]

    def test_string_list_parameter(self):
        parameter = StringListParameter("Roles")
        assert parameter.parse("detector, sis1 ;yig") == ("detector", "sis1", "yig")
        with pytest.raises(ProcedureError):
            parameter.validate("detector")
