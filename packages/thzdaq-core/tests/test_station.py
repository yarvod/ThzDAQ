from pathlib import Path

import pytest
import yaml
from thzdaq_core.errors import StationError
from thzdaq_core.station import (
    DeviceConfig,
    InstrumentConfig,
    Station,
    StationConfig,
    dump_station,
    kinds_for,
    load_station,
    station_from_dict,
    station_to_dict,
)
from thzdaq_instruments import DriverRegistry
from thzdaq_instruments.capabilities import (
    CurrentSource,
    FrequencySource,
    LoadSwitch,
    PowerDetector,
    PowerLevel,
    SpectrumAnalyzer,
    Switchable,
    TunableFilter,
    VoltageCurrentMeter,
    VoltageSource,
)
from thzdaq_instruments.drivers import RigolDP832A
from thzdaq_instruments.errors import InstrumentConnectionError
from thzdaq_instruments.sim import (
    SimPowerSupply,
    SimSignalGenerator,
    SimSisBlock,
)
from thzdaq_instruments.transport import SOCKET, ConnectionSpec, TransportPool
from thzdaq_instruments.transport.fake import FakeLink

EXAMPLE = Path(__file__).parents[3] / "stations" / "2sb.example.yaml"
LAB = Path(__file__).parents[3] / "stations" / "lab.yaml"

TWO_SB_DEVICES = {
    "sis1": "sis_bias_1",
    "sis2": "sis_bias_2",
    "lo": "signal_generator_1",
    "test_tone": "signal_generator_2",
    "if_selector": "power_supply_1:2",
    "yig_power": "power_supply_2:2",
    "detector": "power_meter_1",
    "if_filter": "yig_filter_1:yig_1",
    "load": "chopper_1",
    "spectrum": "spectrum_analyzer_1",
}
TWO_SB_REQUIREMENTS = {
    "sis1": (VoltageSource, VoltageCurrentMeter),
    "sis2": (VoltageSource, VoltageCurrentMeter),
    "lo": (FrequencySource, Switchable, PowerLevel),
    "test_tone": (FrequencySource, Switchable),
    "if_selector": Switchable,
    "yig_power": Switchable,
    "detector": PowerDetector,
    "if_filter": TunableFilter,
    "load": LoadSwitch,
    "spectrum": SpectrumAnalyzer,
}


def sim_station(**devices) -> StationConfig:
    """Supply, generator and SIS block; devices go to the instrument named in 'on'."""
    instruments = {
        "supply": InstrumentConfig("sim.power_supply"),
        "generator": InstrumentConfig("sim.signal_generator"),
        "sis": InstrumentConfig("sim.sis_block", title="SIS block"),
    }
    for device_id, spec in devices.items():
        spec = dict(spec)
        host = spec.pop("on")
        instruments[host].devices[device_id] = DeviceConfig(**spec)
    return StationConfig(name="bench", instruments=instruments)


class TestKinds:
    def test_kinds_per_driver(self):
        sis = kinds_for(SimSisBlock)
        assert set(sis) == {"sis_bias", "sis_coil"}
        assert sis["sis_coil"].accessor == "ctrl" and sis["sis_bias"].needs_channel
        assert [p.name for p in sis["sis_bias"].settings] == [
            "offset_voltage", "offset_current",
        ]  # fmt: skip
        # A generator is one device, supply channels are used as they are
        assert kinds_for(SimPowerSupply) == {} and kinds_for(SimSignalGenerator) == {}

    def test_settings_are_validated(self):
        kind = kinds_for(SimSisBlock)["sis_bias"]
        assert kind.clean({}) == {"offset_voltage": 0.0, "offset_current": 0.0}
        with pytest.raises(StationError, match="unknown settings"):
            kind.clean({"offset": 2})
        with pytest.raises(StationError, match="offset_voltage"):
            kind.clean({"offset_voltage": "much"})


class TestStation:
    def test_devices_list_without_opening(self):
        config = sim_station(
            sis_bias_1={"on": "sis", "kind": "sis_bias", "channel": "DEV4", "title": "b1d4"},
            sis_coil_1={"on": "sis", "kind": "sis_coil", "channel": "DEV3"},
        )  # fmt: skip
        station = Station(config)
        refs = {info.ref: info for info in station.devices()}
        assert list(refs) == [
            "supply", "supply:1", "supply:2", "supply:3",
            "generator", "sis", "sis_bias_1", "sis_coil_1",
        ]  # fmt: skip
        assert refs["sis_bias_1"].title == "b1d4" and refs["supply:2"].kind == "channel"
        assert refs["sis_coil_1"].provides(CurrentSource)
        assert refs["supply:2"].provides(Switchable)
        assert [i.ref for i in station.find(PowerLevel)] == ["generator"]
        assert station.opened == ()

    def test_devices_are_built_once_and_instruments_shared(self):
        config = sim_station(
            sis_bias_1={"on": "sis", "kind": "sis_bias", "channel": "DEV4"},
            sis_bias_2={"on": "sis", "kind": "sis_bias", "channel": "DEV2"},
        )
        config.instruments["generator"].settings = {"frequency_multiplier": 18}
        with Station(config) as station:
            assert station["sis_bias_1"] is station.device("sis_bias_1")
            assert station["sis_bias_1"].instrument is station["sis_bias_2"].instrument
            assert station.opened == ("sis",)
            # A simulator starts configured as the profile says
            assert station["generator"].get_frequency_multiplier() == 18
            assert station["supply:3"] is station.instrument("supply").channel(3)
        assert station.opened == ()

    def test_two_configs_on_one_channel_keep_their_offsets(self):
        config = sim_station(
            sis_bias_1={
                "on": "sis", "kind": "sis_bias", "channel": "DEV4",
                "settings": {"offset_voltage": 4e-5},
            },
            sis_bias_7={
                "on": "sis", "kind": "sis_bias", "channel": "DEV4",
                "settings": {"offset_voltage": -1e-5},
            },
        )  # fmt: skip
        with Station(config) as station:
            one, seven = station["sis_bias_1"], station["sis_bias_7"]
            channel = station.instrument("sis").channel("DEV4")
            seven.get_voltage()
            assert channel.offset_voltage == -1e-5
            one.set_voltage(2e-3)
            assert channel.offset_voltage == 4e-5 and one.offset_voltage == 4e-5
            assert isinstance(one, VoltageSource)

    def test_unknown_kind_and_missing_channel(self):
        config = sim_station(
            weird={"on": "generator", "kind": "sis_bias"},
            coil={"on": "sis", "kind": "sis_coil"},
        )
        with Station(config) as station:
            with pytest.raises(StationError, match="no device kind"):
                station.device("weird")
            with pytest.raises(StationError, match="channel is required"):
                station.device("coil")
            with pytest.raises(StationError, match="no channel 9"):
                station.device("supply:9")

    def test_require_reports_all_problems(self):
        config = sim_station()
        with Station(config) as station:
            found = station.require(
                {"if_selector": "supply:2"}, {"if_selector": Switchable}
            )
            assert set(found) == {"if_selector"}
            with pytest.raises(StationError) as error:
                station.require(
                    {"if_selector": "supply:2", "detector": "generator"},
                    {
                        "if_selector": Switchable,
                        "detector": PowerDetector,
                        "load": LoadSwitch,
                    },
                )
            message = str(error.value)
            assert "detector" in message and "PowerDetector" in message
            assert "no device chosen for 'load'" in message

    def test_validation(self):
        config = sim_station(sis={"on": "sis", "kind": "sis_bias", "channel": "DEV1"})
        with pytest.raises(StationError, match="used twice"):
            config.validate()
        with pytest.raises(StationError):
            StationConfig(
                "bad", instruments={"1st": InstrumentConfig("sim.chopper")}
            ).validate()
        with pytest.raises(StationError):
            Station(sim_station()).instrument("nope")
        assert sim_station().next_id("power_supply") == "power_supply_1"

    def test_reconfigure_reopens_only_changed_instruments(self):
        config = sim_station()
        with Station(config) as station:
            supply = station.instrument("supply")
            station.instrument("generator")
            edited = sim_station()
            edited.instruments["generator"].sim_options = {"max_frequency": 1e9}
            edited.instruments["supply"].title = "Renamed"
            station.reconfigure(edited)
            assert station.opened == ("supply",)
            assert station.instrument("supply") is supply

    def test_real_driver_through_pool(self):
        responses = {":OUTP? CH2": "ON", "*IDN?": "RIGOL TECHNOLOGIES,DP832A"}
        pool = TransportPool(lambda spec: FakeLink(responses))
        rigol = InstrumentConfig(
            "rigol.dp832a", ConnectionSpec(SOCKET, host="h", port=5555)
        )
        station = Station(StationConfig("bench", {"rigol": rigol}), pool=pool)
        assert station["rigol:2"].get_output() is True
        assert station.snapshot()["identities"] == {
            "rigol": "RIGOL TECHNOLOGIES,DP832A"
        }
        use = station.device_use("rigol:2")
        assert (use.driver, use.kind, use.instrument) == (
            "rigol.dp832a", "channel", "rigol",
        )  # fmt: skip
        station.close()
        assert pool.open_links == 0

    def test_connections_reset_and_abort(self):
        pool = TransportPool(
            lambda spec: FakeLink({"*IDN?": "RIGOL", ":OUTP? CH1": "OFF"})
        )
        gpib = dict(host="10.0.0.3", port=1234)
        config = StationConfig(
            "bench",
            instruments={
                "rigol": InstrumentConfig(
                    "rigol.dp832a", ConnectionSpec(SOCKET, host="h", port=5555),
                    title="Rigol",
                ),
                "gen_1": InstrumentConfig(
                    "agilent.e8247c", ConnectionSpec("prologix", gpib=19, **gpib),
                    title="LO",
                ),
                "gen_2": InstrumentConfig(
                    "agilent.e8247c", ConnectionSpec("prologix", gpib=18, **gpib),
                    title="Tone",
                ),
                "chopper": InstrumentConfig("sim.chopper"),
            },
        )  # fmt: skip
        with Station(config, pool=pool) as station:
            connections = {c.label: c for c in station.connections()}
            assert set(connections) == {"Socket h:5555", "Prologix 10.0.0.3:1234"}
            assert connections["Prologix 10.0.0.3:1234"].instruments == ("LO", "Tone")
            assert not connections["Socket h:5555"].open
            station["rigol:1"].get_output()
            rigol = next(c for c in station.connections() if c.label == "Socket h:5555")
            assert rigol.open and not rigol.broken
            station.abort(["rigol:1", "chopper"])
            assert next(c for c in station.connections() if c.key == rigol.key).broken
            assert station["rigol:1"].get_output() is False  # reconnected
            assert station.reset_connection(rigol.key)
            assert "chopper" not in station.opened  # own connection: closed

    def test_simulate_uses_sim_options(self):
        config = StationConfig(
            "bench",
            instruments={
                "power_meter_1": InstrumentConfig(
                    "rs.nrx",
                    ConnectionSpec(SOCKET, host="h", port=5025),
                    options={"aperture_time": 0.05},
                    sim_options={"power": -12.5},
                )
            },
        )
        with Station(config, simulate=True) as station:
            assert station["power_meter_1"].read_power() == -12.5

    def test_failed_instrument_is_reported_by_require(self):
        registry = DriverRegistry()

        class Unreachable(RigolDP832A):
            def __init__(self, transport, **kwargs):
                raise InstrumentConnectionError("no route to host")

        registry.register("broken", Unreachable)
        config = StationConfig(
            "bench",
            instruments={
                "broken": InstrumentConfig(
                    "broken", ConnectionSpec(SOCKET, host="h", port=1)
                )
            },
        )
        pool = TransportPool(lambda spec: FakeLink())
        with Station(config, registry=registry, pool=pool) as station:
            with pytest.raises(StationError, match="no route to host"):
                station.require({"supply": "broken:1"}, {"supply": Switchable})


class TestStorage:
    def test_example_profile_runs_simulated_2sb_bench(self):
        with Station.load(EXAMPLE, simulate=True) as station:
            found = station.require(TWO_SB_DEVICES, TWO_SB_REQUIREMENTS)
            found["lo"].set_frequency(223e9)  # at the mixer: the generator multiplies
            assert found["lo"].get_frequency_multiplier() == 18
            assert found["lo"].get_frequency() == pytest.approx(223e9)
            found["if_selector"].set_output(False)
            found["load"].to_hot()
            assert isinstance(found["detector"].read_power(), float)
            assert found["sis1"].offset_voltage == pytest.approx(3.3e-5)
            assert isinstance(found["sis1"].instrument, SimSisBlock)

    def test_lab_profile_loads(self):
        config = load_station(LAB)
        biases = [d for d, _, spec in config.devices() if spec.kind == "sis_bias"]
        assert len(biases) == 7
        assert Station(config, simulate=True).info("sis_bias_4").instrument == (
            "sis_block_2"
        )

    def test_roundtrip_keeps_everything(self):
        config = load_station(EXAMPLE)
        again = station_from_dict(yaml.safe_load(dump_station(config)))
        assert again == config
        sis = config.instruments["sis_block_1"].connection
        assert sis.read_termination is None and sis.read_delay == 0.05

    def test_short_files_and_channel_zero(self):
        gen = InstrumentConfig("sim.signal_generator")
        gen.devices["coil_1"] = DeviceConfig("sis_coil", channel=0)
        gen.settings = {"frequency_multiplier": 18}
        data = station_to_dict(StationConfig("bench", {"gen": gen}))
        assert data["instruments"]["gen"] == {
            "driver": "sim.signal_generator",
            "settings": {"frequency_multiplier": 18},
            "devices": {"coil_1": {"kind": "sis_coil", "channel": 0}},
        }
        assert data["version"] == 2

    def test_version_1_roles_become_devices(self):
        config = station_from_dict(
            {
                "version": 1,
                "name": "old",
                "instruments": {
                    "sis_block": {"driver": "scontel.sis_block"},
                    "gen": {"driver": "agilent.e8247c"},
                    "nrx": {"driver": "rs.nrx"},
                },
                "roles": {
                    "sis1": {
                        "instrument": "sis_block", "channel": "DEV4",
                        "attributes": {"offset_voltage": 1e-5},
                        "metadata": {"calibration_coefficients": {"a": 1}},
                    },
                    "sis1_ctrl": {
                        "instrument": "sis_block", "channel": "DEV3", "accessor": "ctrl",
                    },
                    "lo": {
                        "instrument": "gen", "adapter": "scaled_frequency",
                        "options": {"multiplier": 18},
                    },
                    "detector": {"instrument": "nrx"},
                },
            }
        )  # fmt: skip
        devices = config.instruments["sis_block"].devices
        assert devices["sis1"].kind == "sis_bias"
        assert devices["sis1"].settings == {"offset_voltage": 1e-5}
        assert devices["sis1"].metadata == {"calibration_coefficients": {"a": 1}}
        assert devices["sis1_ctrl"].kind == "sis_coil"
        assert config.instruments["gen"].devices == {}
        assert config.instruments["gen"].settings == {"frequency_multiplier": 18}
        assert config.instruments["nrx"].devices == {}

    def test_dropped_kinds_of_version_2(self, caplog):
        config = station_from_dict(
            {
                "instruments": {
                    "gen": {
                        "driver": "agilent.e8247c",
                        "devices": {"lo_1": {"kind": "frequency_multiplier",
                                             "settings": {"multiplier": 18}}},
                    },
                    "supply": {
                        "driver": "rigol.dp832a",
                        "devices": {"if_1": {"kind": "sideband_selector", "channel": 2},
                                    "yig_1": {"kind": "switch", "channel": 1}},
                    },
                }
            }
        )  # fmt: skip
        assert config.instruments["gen"].settings == {"frequency_multiplier": 18}
        assert config.instruments["gen"].devices == {}
        assert config.instruments["supply"].devices == {}
        assert "choose the channel in the measurement" in caplog.text

    @pytest.mark.parametrize(
        "data, message",
        [
            ({"version": 3}, "version"),
            ({"instruments": {"a": {"driver": "x", "colour": 1}}}, "unknown keys"),
            ({"instruments": {"a": {}}}, "driver is required"),
            (
                {"instruments": {"a": {"driver": "x", "connection": {"kind": "usb"}}}},
                "Invalid connection",
            ),
            (
                {
                    "instruments": {
                        "a": {"driver": "x", "connection": {"kind": "socket", "ip": 1}}
                    }
                },
                "Unknown connection fields",
            ),
            (
                {
                    "instruments": {
                        "a": {"driver": "x", "devices": {"d": {"channel": 1}}}
                    }
                },
                "kind is required",
            ),
            ({"roles": {}}, "unknown keys"),
        ],
    )
    def test_invalid_profiles(self, data, message):
        with pytest.raises(StationError, match=message):
            station_from_dict(data)

    def test_exponent_numbers_are_floats(self, tmp_path):
        path = tmp_path / "bench.yaml"
        path.write_text(
            "name: b\ninstruments:\n  gen:\n    driver: sim.signal_generator\n"
            "    sim_options: {max_frequency: 500.0e9, min_frequency: 1e3}\n",
            encoding="utf-8",
        )
        options = load_station(path).instruments["gen"].sim_options
        assert options == {"max_frequency": 500e9, "min_frequency": 1e3}

    def test_missing_file(self, tmp_path):
        with pytest.raises(StationError, match="Can't read"):
            load_station(tmp_path / "nope.yaml")

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("instruments: [", encoding="utf-8")
        with pytest.raises(StationError, match="invalid YAML"):
            load_station(path)


def test_snapshot_asks_only_the_measurement_instruments():
    """A chopper opened earlier and not answering broke the start of an I-V."""
    from thzdaq_core.station import InstrumentConfig, Station, StationConfig

    config = StationConfig(
        "bench",
        {
            "supply": InstrumentConfig("rigol.dp832a", simulate=True),
            "chopper": InstrumentConfig("chopper.modbus", simulate=True),
        },
    )
    station = Station(config)
    station.instrument("supply")
    chopper = station.instrument("chopper")
    asked = []

    def silent():
        asked.append("chopper")
        raise ConnectionResetError(10054, "the remote host closed the connection")

    chopper.identify = silent
    snapshot = station.snapshot(["supply:1"])
    assert list(snapshot["identities"]) == ["supply"] and asked == []
    # Asked anyway (all opened instruments): recorded, never raised
    everything = station.snapshot()["identities"]
    assert everything["chopper"].startswith("error: ConnectionResetError")
    station.close()
