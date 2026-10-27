import pytest
from thzdaq_core.data import COMPLETED, DeviceUse
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements import MeasurementRunner, StringListParameter
from thzdaq_core.measurements.procedures import Demagnetize, Monitor
from thzdaq_core.measurements.procedures.monitor import (
    default_quantities,
    monitor_quantities,
    plot_for,
)
from thzdaq_instruments.quantities import quantities_of
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
    SimCompressor,
    SimPowerMeter,
    SimPowerSupply,
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

            def snapshot(self, refs=None):
                return {}

        procedure = Demagnetize(minimum=-10e-3, maximum=10e-3, step=5e-3, step_delay=0)
        dataset = MeasurementRunner(Bench()).run(procedure)
        assert dataset.status == COMPLETED
        assert len(dataset.records("coil")) == procedure.estimate_steps()
        assert coil.get_current() == pytest.approx(0, abs=1e-12)
        with pytest.raises(ProcedureError):
            Demagnetize(minimum=1e-3, maximum=-1e-3).validate()


class TestMonitor:
    def test_what_is_read_by_default(self):
        def keys(port):
            return [q.key for q in default_quantities(quantities_of(port))]

        assert keys(SimSisBlock().channel("DEV4")) == ["voltage", "current"]
        assert keys(SimPowerMeter()) == ["power"]
        assert keys(SimSisBlock().ctrl("DEV3")) == ["coil_current"]  # what it reports
        assert keys(SimChopper()) == []
        supply = [
            q.key
            for q in monitor_quantities(quantities_of(SimPowerSupply().channel(1)))
        ]
        assert {"voltage_set", "current_set", "voltage", "current"} <= set(supply)

    def test_graph_by_unit(self):
        plots = {
            q.key: plot_for(q)
            for port in (SimPowerMeter(), SimSisBlock().ctrl("DEV3"), SimCompressor())
            for q in monitor_quantities(quantities_of(port))
        }
        assert plots["power"] == "P-t" and plots["current_set"] == "Coil-t"
        assert plots["temperature_1"] == "T-t" and plots["pressure_1"] == "p-t"

    def run_monitor(self, ports, **parameters):
        class Bench:
            def device_use(self, ref):
                return DeviceUse(ref)

            def require(self, devices, requirements):
                return {slot: ports[slot] for slot in requirements}

            def snapshot(self, refs=None):
                return {}

        return MeasurementRunner(Bench()).run(Monitor(**parameters))

    def test_monitor_for_a_duration(self):
        ports = {
            "detector": SimPowerMeter(power=-20.0),
            "cryostat": SimTemperatureController().channel("A"),
        }
        dataset = self.run_monitor(
            ports, watch=("detector", "cryostat"), interval=0.02, duration=0.1
        )
        samples = dataset.records("samples")
        assert dataset.status == COMPLETED
        assert {s["device"] for s in samples} == {"detector", "cryostat"}
        assert 4 <= len(samples) // 2 <= 7
        temperatures = Monitor.plots[1].curves(samples)
        assert list(temperatures) == [("cryostat", "Temperature")]
        assert {p[1] for p in temperatures[("cryostat", "Temperature")]} == {4.2}
        assert not Monitor.plots[0].curves(
            [s for s in samples if s["device"] == "cryostat"]
        )

    def test_one_quantity_of_a_device(self):
        sis = SimSisBlock().channel("DEV4")
        sis.set_voltage(2e-3)
        dataset = self.run_monitor(
            {"sis": sis}, watch=("sis/voltage",), interval=0.02, duration=0.05
        )
        samples = dataset.records("samples")
        assert {s["key"] for s in samples} == {"voltage"}
        assert samples[0]["value"] == pytest.approx(2e-3)
        assert samples[0]["plot"] == "V-t"
        failed = self.run_monitor({"sis": sis}, watch=("sis/power",), duration=0.05)
        assert failed.status == "failed" and "power" in failed.error

    def test_plot_window(self):
        assert Monitor(window=120).plot_window() == 120
        assert Monitor(window=0).plot_window() is None

    def test_string_list_parameter(self):
        parameter = StringListParameter("Roles")
        assert parameter.parse("detector, sis1 ;yig") == ("detector", "sis1", "yig")
        with pytest.raises(ProcedureError):
            parameter.validate("detector")
