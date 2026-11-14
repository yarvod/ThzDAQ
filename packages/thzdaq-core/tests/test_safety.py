"""Protection of instruments and samples: passports, bench limits, steps, safe state."""

import threading

import pytest
from test_station import sim_station
from thzdaq_core.application.runner import Cancelled, MeasurementRunner, RampPause
from thzdaq_core.adapters.json_store import MeasurementStore
from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.measurements.procedures.iv_curve import IVCurve
from thzdaq_core.domain.station.config import InstrumentConfig, StationConfig
from thzdaq_core.domain.station.profile import station_from_dict, station_to_dict
from thzdaq_core.domain.station.safety import Safety, SafetyLimit
from thzdaq_core.domain.station.station import Station
from thzdaq_instruments.errors import LimitError
from thzdaq_instruments.transport import SOCKET, ConnectionSpec, TransportPool
from thzdaq_instruments.transport.fake import FakeLink

SAFETY = {
    "limits": {
        "supply:1": {
            "voltage_set": {"min": 0, "max": 12, "warn_max": 10, "step": 1, "rate": 2}
        },
        "sis_bias_1": {"voltage_set": {"min": -5e-3, "max": 5e-3}},
    },
    "safe_state": {"supply:1": {"voltage_set": 0, "output": False}},
    "hardware_protection": True,
}


def bench(**safety) -> StationConfig:
    config = sim_station(
        sis_bias_1={"on": "sis", "kind": "sis_bias", "channel": "DEV4"}
    )
    data = station_to_dict(config)
    data["safety"] = {**SAFETY, **safety}
    return station_from_dict(data)


class Waits:
    """A pause that only counts."""

    def __init__(self):
        self.seconds = []

    def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


def written(channel, method="set_voltage"):
    """Values the part gets from now on, through the given method."""
    values = []
    original = getattr(channel, method)

    def record(value, *args, **kwargs):
        values.append(value)
        return original(value, *args, **kwargs)

    setattr(channel, method, record)
    return values


class TestProfile:
    def test_the_safety_section_goes_both_ways(self):
        config = bench()
        limit = config.safety.limits["supply:1"]["voltage_set"]
        assert limit == SafetyLimit(0.0, 12.0, warn_maximum=10.0, step=1.0, rate=2.0)
        assert config.safety.safe_state["supply:1"] == {
            "voltage_set": 0,
            "output": False,
        }
        again = station_from_dict(station_to_dict(config))
        assert again.safety == config.safety
        assert "safety" not in station_to_dict(sim_station())  # nothing when empty

    @pytest.mark.parametrize(
        "safety, problem",
        [
            ({"limits": {"supply:1": {"voltage_set": {"max": "high"}}}}, "a number"),
            ({"limits": {"supply:1": {"voltage_set": {"maximum": 1}}}}, "unknown keys"),
            (
                {"limits": {"supply:1": {"voltage_set": {"min": 2, "max": 1}}}},
                "above max",
            ),
            ({"limits": {"supply:1": {"voltage_set": {"rate": 1}}}}, "rate needs step"),
            (
                {"limits": {"supply:1": {"voltage_set": {"max": 1, "warn_max": 2}}}},
                "warn_max",
            ),
            ({"limits": {"nowhere": {"voltage_set": {"max": 1}}}}, "no device"),
            ({"limits": []}, "mapping"),
        ],
    )
    def test_a_wrong_section_is_refused(self, safety, problem):
        data = station_to_dict(sim_station())
        data["safety"] = safety
        with pytest.raises(StationError, match=problem):
            station_from_dict(data)

    @pytest.mark.parametrize(
        "safety, problem",
        [
            ({"limits": {"supply:1": {"power": {"max": 1}}}}, "no number it sets"),
            ({"limits": {"supply:7": {"voltage_set": {"max": 1}}}}, "supply:7"),
            ({"safe_state": {"supply:1": {"voltage": 0}}}, "does not set voltage"),
            ({"safe_state": {"supply:1": {"output": "maybe"}}}, "not on or off"),
        ],
    )
    def test_the_station_refuses_safety_that_guards_nothing(self, safety, problem):
        with pytest.raises(StationError, match=problem):
            Station(bench(**{"limits": {}, "safe_state": {}, **safety}), pause=Waits())


class TestGuard:
    def test_outside_the_passport_nothing_reaches_the_instrument(self):
        links = []
        pool = TransportPool(lambda spec: links.append(FakeLink()) or links[-1])
        rigol = InstrumentConfig(
            "rigol.dp832a", ConnectionSpec(SOCKET, host="h", port=5555)
        )
        station = Station(
            StationConfig("bench", {"rigol": rigol}), pause=Waits(), pool=pool
        )
        with pytest.raises(
            LimitError, match=r"rigol:3 voltage_set: 6 V is above 5 V \(passport\)"
        ):
            station["rigol:3"].set_voltage(6.0)
        assert all(not link.events for link in links)
        station["rigol:1"].set_voltage(6.0)  # CH1 takes 30 V
        assert ("w", ":SOURce1:VOLTage 6.0") in links[0].events
        station.close()

    def test_outside_the_bench_limits_is_refused(self):
        station = Station(bench(), pause=Waits())
        bias = station["sis_bias_1"]
        values = written(bias.target, "set_voltage")
        with pytest.raises(LimitError, match=r"\(bench\)"):
            bias.set_voltage(6e-3)
        with pytest.raises(LimitError):
            bias.set_voltage_precise(-6e-3, max_iterations=3)
        assert values == []
        bias.set_voltage(4e-3)
        assert values == [4e-3]

    def test_a_large_change_goes_in_steps_at_the_rate(self):
        waits = Waits()
        station = Station(bench(), pause=waits)
        supply = station["supply:1"]
        values = written(supply.target)
        supply.set_voltage(3.0)
        assert values == pytest.approx([1.0, 2.0, 3.0])
        assert waits.seconds == pytest.approx([0.5, 0.5])  # 1 V at 2 V/s
        supply.set_voltage(3.5)  # within a step: no ladder, no wait
        assert values[-1] == 3.5 and len(waits.seconds) == 2

    def test_the_value_before_comes_from_what_was_written(self):
        station = Station(bench(), pause=Waits())
        channel = station["supply:1"].target
        reads = []
        original = channel.get_voltage
        channel.get_voltage = lambda: reads.append(1) or original()
        for value in (0.5, 1.0, 1.5, 2.0):
            station["supply:1"].set_voltage(value)
        assert len(reads) == 1  # read once, at the first change

    def test_after_a_raw_write_a_change_starts_from_the_device(self):
        """A raw write changed the device past its guard: the next change reads
        where it starts from instead of the setpoint written last."""
        station = Station(bench(), pause=Waits())
        supply = station["supply:1"]
        supply.set_voltage(1.0)
        supply.target.set_voltage(3.0)  # as a raw command would, unguarded
        station.forget_setpoints("supply")
        values = written(supply.target)
        supply.set_voltage(3.5)
        assert values == [3.5]  # within a step of 3 V: no ladder from 1 V

    def test_a_cancel_stops_a_ladder_at_once(self):
        cancel = threading.Event()
        pause = RampPause(cancel)
        station = Station(bench(), pause=Waits())
        supply = station["supply:1"].for_run(pause)
        values = written(supply.target)
        cancel.set()
        with pytest.raises(Cancelled):
            supply.set_voltage(5.0)
        assert values == [1.0]
        assert station["supply:1"].setpoints["voltage_set"] == 1.0
        pause.restoring = True  # restoring at the end ramps to the end
        supply.set_voltage(0.0)
        assert values == [1.0, 0.0]

    def test_supplies_keep_the_maxima_themselves(self):
        station = Station(bench(), pause=Waits())
        channel = station["supply:1"].target
        assert channel.protection == (12.0, None)
        edited = bench()
        edited.safety.limits["supply:1"]["current_set"] = SafetyLimit(maximum=0.5)
        station.reconfigure(edited)
        assert channel.protection == (12.0, 0.5)
        unprotected = Station(bench(hardware_protection=False), pause=Waits())
        assert unprotected["supply:1"].target.protection == (None, None)


class TestBeforeTheStart:
    def test_a_sweep_beyond_the_limits_does_not_start(self, tmp_path):
        station = Station(bench(), pause=Waits())
        store = MeasurementStore(tmp_path)
        runner = MeasurementRunner(station, store)
        with pytest.raises(
            StationError, match=r"bias: sis_bias_1 voltage_set: 0\.007 V"
        ):
            runner.run(IVCurve(voltage=(0.0, 7e-3, 8)), devices={"bias": "sis_bias_1"})
        assert not list(tmp_path.iterdir())
        done = runner.run(
            IVCurve(voltage=(-5e-3, 5e-3, 3), first_point_delay=0, settle_time=0),
            devices={"bias": "sis_bias_1"},
        )
        assert done.status == "completed"

    def test_a_procedure_says_what_it_sets(self):
        planned = IVCurve(voltage=(1e-3, 3e-3, 5)).planned()
        assert planned == [("bias", "voltage_set", (1e-3, 3e-3))]


def test_safety_is_empty_by_default():
    assert StationConfig("bench").safety == Safety()
