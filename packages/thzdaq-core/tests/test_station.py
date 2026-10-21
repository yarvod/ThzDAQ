from pathlib import Path

import pytest
import yaml
from thzdaq_core.errors import StationError
from thzdaq_core.station import (
    InstrumentConfig,
    RoleConfig,
    ScaledFrequencySource,
    SidebandSelector,
    Station,
    StationConfig,
    SwitchPort,
    dump_station,
    load_station,
    register_adapter,
    station_from_dict,
    station_to_dict,
)
from thzdaq_core.station.ports import ADAPTERS, PortAdapter
from thzdaq_instruments import DriverRegistry
from thzdaq_instruments.capabilities import (
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

TWO_SB_REQUIREMENTS = {
    "sis1": (VoltageSource, VoltageCurrentMeter),
    "sis2": (VoltageSource, VoltageCurrentMeter),
    "lo": (FrequencySource, Switchable, PowerLevel),
    "test_tone": (FrequencySource, Switchable),
    "if_selector": Switchable,
    "yig_power": Switchable,
    "detector": PowerDetector,
    "yig_filter": TunableFilter,
    "load": LoadSwitch,
    "spectrum": SpectrumAnalyzer,
}


def sim_station(**roles) -> StationConfig:
    return StationConfig(
        name="bench",
        instruments={
            "supply": InstrumentConfig("sim.power_supply"),
            "generator": InstrumentConfig("sim.signal_generator"),
            "sis": InstrumentConfig("sim.sis_block"),
        },
        roles={name: RoleConfig(**spec) for name, spec in roles.items()},
    )


class TestPorts:
    def test_switch_port_inverts(self):
        channel = SimPowerSupply().channel(1)
        port = SwitchPort(channel, inverted=True)
        port.set_output(True)
        assert channel.get_output() is False and port.get_output() is True

    def test_scaled_frequency_keeps_other_abilities(self):
        generator = SimSignalGenerator()
        lo = ScaledFrequencySource(generator, multiplier=18)
        lo.set_frequency(223e9)
        assert generator.get_frequency() == pytest.approx(223e9 / 18)
        assert lo.get_frequency() == pytest.approx(223e9)
        lo.set_output(True)  # delegated to the generator
        assert generator.get_output() and isinstance(lo, Switchable)

    def test_sideband_selector(self):
        channel = SimPowerSupply().channel(2)
        selector = SidebandSelector(channel, upper_when_on=False)
        selector.select("upper")
        assert channel.get_output() is False and selector.selected() == "upper"
        selector.select("lower")
        assert channel.get_output() is True
        with pytest.raises(StationError):
            selector.select("middle")

    def test_new_adapters_are_pluggable(self):
        class Halved(PortAdapter):
            def set_voltage(self, voltage):
                self.target.set_voltage(voltage / 2)

        register_adapter("halved", Halved)
        try:
            config = sim_station(
                bias={"instrument": "supply", "channel": 1, "adapter": "halved"}
            )
            with Station(config) as station:
                station["bias"].set_voltage(10)
                assert station.instrument("supply").channel(1).get_voltage() == 5
            with pytest.raises(StationError):
                register_adapter("halved", Halved)
        finally:
            ADAPTERS.pop("halved")


class TestStation:
    def test_roles_are_built_once_and_instruments_shared(self):
        config = sim_station(
            sis1={"instrument": "sis", "channel": "DEV4"},
            sis2={"instrument": "sis", "channel": "DEV2"},
            lo={
                "instrument": "generator",
                "adapter": "scaled_frequency",
                "options": {"multiplier": 18},
            },
        )
        with Station(config) as station:
            assert station["sis1"] is station.role("sis1")
            assert station["sis1"].instrument is station["sis2"].instrument
            assert station.opened == ("sis",)
            station["lo"].set_frequency(18e9)
            assert station.instrument("generator").get_frequency() == pytest.approx(1e9)
        assert station.opened == ()

    def test_attributes_are_applied_and_checked(self):
        config = sim_station(
            sis1={
                "instrument": "sis",
                "channel": "DEV4",
                "attributes": {"offset_voltage": 4e-5},
            },
            typo={
                "instrument": "sis",
                "channel": "DEV2",
                "attributes": {"ofset_voltage": 1},
            },
        )
        with Station(config) as station:
            assert station["sis1"].offset_voltage == 4e-5
            with pytest.raises(StationError):
                station.role("typo")

    def test_accessor_reaches_other_parts(self):
        config = sim_station(
            coil={"instrument": "sis", "channel": "DEV3", "accessor": "ctrl"},
            bad={"instrument": "generator", "channel": 1, "accessor": "heater"},
        )
        with Station(config) as station:
            station["coil"].set_current(5e-3)
            assert station.instrument("sis").ctrl("DEV3").get_current() == 5e-3
            with pytest.raises(StationError):
                station.role("bad")

    def test_require_reports_all_problems(self):
        config = sim_station(
            if_selector={"instrument": "supply", "channel": 2},
            detector={"instrument": "generator"},
        )
        with Station(config) as station:
            ports = station.require({"if_selector": Switchable})
            assert set(ports) == {"if_selector"}
            with pytest.raises(StationError) as error:
                station.require(
                    {
                        "if_selector": Switchable,
                        "detector": PowerDetector,
                        "load": LoadSwitch,
                    }
                )
            message = str(error.value)
            assert "detector" in message and "PowerDetector" in message
            assert "'load' is not configured" in message
            assert station.missing_roles(["load", "detector"]) == ("load",)

    def test_validation(self):
        with pytest.raises(StationError):
            StationConfig("bad", roles={"lo": RoleConfig("nowhere")}).validate()
        with pytest.raises(StationError):
            StationConfig(
                "bad", instruments={"1st": InstrumentConfig("sim.chopper")}
            ).validate()
        with pytest.raises(StationError):
            Station(sim_station()).instrument("nope")

    def test_real_driver_through_pool(self):
        responses = {":OUTP? CH2": "ON", "*IDN?": "RIGOL TECHNOLOGIES,DP832A"}
        pool = TransportPool(lambda spec: FakeLink(responses))
        config = StationConfig(
            "bench",
            instruments={
                "rigol": InstrumentConfig(
                    "rigol.dp832a", ConnectionSpec(SOCKET, host="h", port=5555)
                )
            },
            roles={
                "if_selector": RoleConfig(
                    "rigol", channel=2, adapter="sideband_selector"
                )
            },
        )
        station = Station(config, pool=pool)
        assert station["if_selector"].selected() == "upper"
        assert station.snapshot()["identities"] == {
            "rigol": "RIGOL TECHNOLOGIES,DP832A"
        }
        station.close()
        assert pool.open_links == 0

    def test_simulate_uses_sim_options(self):
        config = StationConfig(
            "bench",
            instruments={
                "nrx": InstrumentConfig(
                    "rs.nrx",
                    ConnectionSpec(SOCKET, host="h", port=5025),
                    options={"aperture_time": 0.05},
                    sim_options={"power": -12.5},
                )
            },
            roles={"detector": RoleConfig("nrx")},
        )
        with Station(config, simulate=True) as station:
            assert station["detector"].read_power() == -12.5

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
            roles={"supply": RoleConfig("broken", channel=1)},
        )
        pool = TransportPool(lambda spec: FakeLink())
        with Station(config, registry=registry, pool=pool) as station:
            with pytest.raises(StationError, match="no route to host"):
                station.require({"supply": Switchable})


class TestStorage:
    def test_example_profile_runs_simulated_2sb_bench(self):
        with Station.load(EXAMPLE, simulate=True) as station:
            ports = station.require(TWO_SB_REQUIREMENTS)
            ports["lo"].set_frequency(223e9)
            assert station.instrument("lo_generator").get_frequency() == pytest.approx(
                223e9 / 18
            )
            ports["if_selector"].select("lower")
            ports["load"].to_hot()
            assert isinstance(ports["detector"].read_power(), float)
            assert ports["sis1"].offset_voltage == pytest.approx(3.3e-5)
            assert isinstance(ports["sis1"].instrument, SimSisBlock)

    def test_roundtrip_keeps_everything(self):
        config = load_station(EXAMPLE)
        again = station_from_dict(yaml.safe_load(dump_station(config)))
        assert again == config
        sis = config.instruments["sis_block"].connection
        assert sis.read_termination is None and sis.read_delay == 0.05

    def test_short_files_and_channel_zero(self):
        config = StationConfig(
            "bench",
            instruments={"gen": InstrumentConfig("sim.signal_generator")},
            roles={"lo": RoleConfig("gen", channel=0)},
        )
        data = station_to_dict(config)
        assert data["instruments"]["gen"] == {"driver": "sim.signal_generator"}
        assert data["roles"]["lo"] == {"instrument": "gen", "channel": 0}

    @pytest.mark.parametrize(
        "data, message",
        [
            ({"version": 2}, "version"),
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
            ({"roles": {"lo": {"channel": 1}}}, "instrument is required"),
        ],
    )
    def test_invalid_profiles(self, data, message):
        with pytest.raises(StationError, match=message):
            station_from_dict(data)

    def test_missing_file(self, tmp_path):
        with pytest.raises(StationError, match="Can't read"):
            load_station(tmp_path / "nope.yaml")

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("roles: [", encoding="utf-8")
        with pytest.raises(StationError, match="invalid YAML"):
            load_station(path)
