import subprocess
import sys

import pytest
from thzdaq_instruments import (
    ConfigurationError,
    DriverRegistry,
    InstrumentResponseError,
    ScpiInstrument,
    UnknownDriverError,
    default_registry,
)
from thzdaq_instruments.capabilities import (
    FrequencySource,
    Identifiable,
    PowerDetector,
    Switchable,
    VoltageCurrentMeter,
    VoltageSource,
)
from thzdaq_instruments.instrument import Channel, Instrument
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.sim import SimPowerSupply
from thzdaq_instruments.transport import SOCKET, ConnectionSpec, TransportPool
from thzdaq_instruments.transport.fake import FakeLink, fake_transport


class DemoChannel(Channel):
    instrument: "DemoSupply"

    def set_output(self, value: bool) -> None:
        self.instrument.write(f":OUTP CH{self.key},{'ON' if value else 'OFF'}")

    def get_output(self) -> bool:
        return self.instrument.query_bool(f":OUTP? CH{self.key}")

    def measure(self) -> ChannelReading:
        voltage, current, _ = self.instrument.query(f":MEAS:ALL? CH{self.key}").split(
            ","
        )
        return ChannelReading(float(voltage), float(current))


class DemoSupply(ScpiInstrument):
    channel_class = DemoChannel
    channel_keys = (1, 2)


class TestScpiInstrument:
    def make(self, responses):
        transport, link = fake_transport(responses)
        return DemoSupply(transport, name="demo"), link

    def test_typed_queries(self):
        supply, _ = self.make({"V?": "1.5E+00", "N?": "+3", "B?": "ON", "C?": "0"})
        assert supply.query_float("V?") == 1.5
        assert supply.query_int("N?") == 3
        assert supply.query_bool("B?") is True
        assert supply.query_bool("C?") is False

    @pytest.mark.parametrize("method", ["query_float", "query_int", "query_bool"])
    def test_garbage_answer_is_response_error(self, method):
        supply, _ = self.make({"X?": "ERROR"})
        with pytest.raises(InstrumentResponseError):
            getattr(supply, method)("X?")

    def test_channels_are_cached_and_validated(self):
        supply, link = self.make({":OUTP? CH2": "ON", ":MEAS:ALL? CH2": "5,0.1,0.5"})
        channel = supply.channel(2)
        assert supply.channel(2) is channel
        assert channel.name == "demo/2"
        assert channel.get_output() is True
        assert channel.measure() == ChannelReading(5.0, 0.1)
        assert [c.key for c in supply.channels] == [1, 2]
        with pytest.raises(ConfigurationError):
            supply.channel(3)

    def test_instrument_without_channels(self):
        with pytest.raises(ConfigurationError):
            Instrument().channel(1)

    def test_context_manager_closes_transport(self):
        transport, _ = fake_transport()
        with DemoSupply(transport):
            pass
        assert transport.closed


class TestRegistry:
    def test_capabilities_are_derived_from_classes(self):
        registry = DriverRegistry()
        registry.register("demo.supply", DemoSupply, title="Demo")
        info = registry.get("demo.supply")
        assert info.capabilities == (Identifiable,)
        assert set(info.channel_capabilities) == {Switchable, VoltageCurrentMeter}
        assert registry.find(Switchable) == [info]
        assert registry.find(FrequencySource) == []

    def test_duplicate_and_unknown_keys(self):
        registry = DriverRegistry()
        registry.register("demo.supply", DemoSupply)
        with pytest.raises(ConfigurationError):
            registry.register("demo.supply", DemoSupply)
        registry.register("demo.supply", DemoSupply, title="v2", replace=True)
        assert registry.get("demo.supply").title == "v2"
        with pytest.raises(UnknownDriverError):
            registry.get("missing")

    def test_decorator_registration(self):
        registry = DriverRegistry()

        @registry.register("demo.decorated", title="Decorated")
        class Decorated(DemoSupply):
            pass

        assert registry.get("demo.decorated").cls is Decorated

    def test_open_uses_pool_transport(self):
        links = []

        def factory(spec):
            link = FakeLink({":OUTP? CH1": "OFF"})
            links.append(link)
            return link

        pool = TransportPool(factory)
        registry = DriverRegistry()
        registry.register("demo.supply", DemoSupply)
        spec = ConnectionSpec(SOCKET, host="10.0.0.5", port=5555)

        supply = registry.open("demo.supply", spec, pool=pool, name="IF switch")
        assert supply.name == "IF switch"
        assert supply.channel(1).get_output() is False
        supply.close()
        assert pool.open_links == 0 and links[0].close_count == 1

    def test_failed_constructor_releases_transport(self):
        class Broken(DemoSupply):
            def __init__(self, transport, **kwargs):
                raise InstrumentResponseError("wrong model")

        pool = TransportPool(lambda spec: FakeLink())
        registry = DriverRegistry()
        registry.register("demo.broken", Broken)
        with pytest.raises(InstrumentResponseError):
            registry.open(
                "demo.broken", ConnectionSpec(SOCKET, host="h", port=1), pool=pool
            )
        assert pool.open_links == 0

    def test_open_requires_connection(self):
        registry = DriverRegistry()
        registry.register("demo.supply", DemoSupply)
        with pytest.raises(ConfigurationError):
            registry.open("demo.supply")

    def test_simulate_uses_attached_simulator(self):
        registry = DriverRegistry()
        registry.register("demo.supply", DemoSupply, sim=SimPowerSupply)
        supply = registry.open(
            "demo.supply", simulate=True, name="bench", max_voltage=5
        )
        assert isinstance(supply, SimPowerSupply)
        assert supply.name == "bench" and supply.max_voltage == 5

        registry.register("demo.nosim", DemoSupply)
        with pytest.raises(ConfigurationError):
            registry.open("demo.nosim", simulate=True)

    def test_default_registry_has_simulators(self):
        registry = default_registry()
        assert "sim.power_supply" in registry
        detectors = [info.key for info in registry.find(PowerDetector)]
        assert detectors == ["sim.power_meter"]
        sources = {info.key for info in registry.find(VoltageSource)}
        assert sources == {"sim.power_supply", "sim.sis_block"}
        assert isinstance(registry.open("sim.chopper"), Instrument)


def test_package_does_not_import_gui_or_numpy():
    code = (
        "import sys, thzdaq_instruments, thzdaq_instruments.sim, "
        "thzdaq_instruments.transport.fake;"
        "print(sorted(m for m in sys.modules "
        "if m.split('.')[0] in ('PySide6', 'pyqtgraph', 'numpy', 'store', 'interface')))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
