import json
import math
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from emulators import (
    AgilentEmulator,
    FakeJsonClient,
    HmpEmulator,
    KeithleyEmulator,
    MotorRegisters,
    NrxEmulator,
    RigolEmulator,
    SisEmulator,
)
from thzdaq_instruments import default_registry
from thzdaq_instruments.capabilities import PowerDetector, VoltageSource
from thzdaq_instruments.drivers import (
    AgilentE8247C,
    ArduinoGrid,
    Keithley2200,
    ModbusChopper,
    NiYigFilter,
    RigolDP832A,
    RohdeSchwarzHMP2030,
    RohdeSchwarzNRX,
    ScontelSisBlock,
    SumitomoF70,
    SumitomoF70Rest,
)
from thzdaq_instruments.drivers import chopper as chopper_module
from thzdaq_instruments.errors import (
    ConfigurationError,
    InstrumentConnectionError,
    InstrumentError,
    InstrumentResponseError,
    InstrumentTimeoutError,
)
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.sim import SimPowerSupply, SimYigFilter
from thzdaq_instruments.transport import (
    HTTP,
    MODBUS_TCP,
    ConnectionSpec,
    TransportPool,
)
from thzdaq_instruments.transport.http import JsonHttpClient
from thzdaq_instruments.transport.modbus import (
    PymodbusRegisters,
    int32_to_registers,
    registers_to_int32,
)


def make(cls, emulator, **options):
    transport, link = emulator.transport()
    return cls(transport, **options), link


class TestPowerSupplies:
    def test_rigol_commands_and_measure(self):
        emulator = RigolEmulator()
        supply, link = make(RigolDP832A, emulator)
        channel = supply.channel(2)
        channel.set_voltage(5)
        channel.set_output(True)
        assert channel.measure() == ChannelReading(5.0, 0.05)
        assert link.written[:2] == [":SOURce2:VOLTage 5", ":OUTP CH2,ON"]
        assert supply.test()
        assert emulator.errors == []

    def test_rigol_garbage_measure(self):
        supply, _ = make(RigolDP832A, RigolEmulator())
        supply.transport.link._responder = lambda command: "ERR"
        with pytest.raises(InstrumentResponseError):
            supply.channel(1).measure()

    def test_hmp_selects_channel_for_every_command(self):
        emulator = HmpEmulator()
        supply, link = make(RohdeSchwarzHMP2030, emulator)
        supply.channel(2).set_voltage(3.3)
        supply.channel(3).set_output(True)
        assert supply.channel(2).get_voltage() == 3.3
        assert emulator.channels[2].voltage == 3.3
        assert emulator.channels[3].output and not emulator.channels[2].output
        assert link.written[:4] == [
            "INST:NSEL 2",
            "SOUR:VOLT:LEV:AMPL 3.3",
            "INST:NSEL 3",
            "OUTP:STAT 1",
        ]
        assert emulator.errors == []

    def test_hmp_channel_selection_is_atomic(self):
        emulator = HmpEmulator()
        supply, link = make(RohdeSchwarzHMP2030, emulator)
        link.delay = 0.0005

        def worker(channel, voltage):
            for _ in range(20):
                supply.channel(channel).set_voltage(voltage)

        threads = [
            threading.Thread(target=worker, args=(1, 1.0)),
            threading.Thread(target=worker, args=(2, 2.0)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert emulator.channels[1].voltage == 1.0
        assert emulator.channels[2].voltage == 2.0

    def test_hmp_general_output(self):
        emulator = HmpEmulator()
        supply, _ = make(RohdeSchwarzHMP2030, emulator)
        supply.set_general_output(True)
        assert supply.get_general_output() and emulator.general

    def test_keithley_single_channel(self):
        emulator = KeithleyEmulator()
        supply, _ = make(Keithley2200, emulator)
        channel = supply.channel(1)
        channel.set_voltage(10)
        channel.set_output(True)
        assert channel.measure() == ChannelReading(10.0, 0.1)
        with pytest.raises(ConfigurationError):
            supply.channel(2)
        assert emulator.errors == []

    def test_vendor_must_implement_primitives(self):
        from thzdaq_instruments.drivers.power_supply import ScpiPowerSupply

        with pytest.raises(TypeError):
            ScpiPowerSupply(None)


class TestAgilent:
    @pytest.mark.parametrize(
        "amplitude, attenuation, alc",
        [(5, 0, 5), (-5, 0, -5), (-25, 20, -5), (-100, 90, -10), (-130, 90, -40)],
    )
    def test_amplitude_through_attenuator(self, amplitude, attenuation, alc):
        emulator = AgilentEmulator()
        generator, link = make(AgilentE8247C, emulator)
        generator.set_amplitude(amplitude)
        assert (emulator.attenuation, emulator.alc) == (attenuation, alc)
        assert link.written[0] == ":POW:ALC:LEV 0"
        assert generator.get_amplitude() == pytest.approx(amplitude)

    def test_amplitude_limit(self):
        generator, _ = make(AgilentE8247C, AgilentEmulator())
        with pytest.raises(ConfigurationError):
            generator.set_amplitude(26)

    def test_output_frequency_multiplier(self):
        emulator = AgilentEmulator()
        generator, _ = make(AgilentE8247C, emulator)
        generator.set_frequency(12.5e9)
        generator.set_frequency_multiplier(18)
        assert generator.get_frequency() == 12.5e9
        assert generator.get_frequency_multiplier() == 18
        assert generator.test()
        assert emulator.errors == []


class TestNrx:
    @pytest.mark.parametrize("unit", ["DBM", "W", "DBUV"])
    def test_read_power_is_dbm_in_any_unit(self, unit):
        emulator = NrxEmulator(power_dbm=-23.5)
        emulator.unit = unit
        meter, link = make(RohdeSchwarzNRX, emulator)
        assert meter.read_power() == pytest.approx(-23.5, abs=1e-3)
        assert meter.read_power() == pytest.approx(-23.5, abs=1e-3)

    def test_unit_changed_on_the_front_panel_is_followed(self):
        emulator = NrxEmulator(power_dbm=-23.5)
        meter, _ = make(RohdeSchwarzNRX, emulator)
        assert meter.read_power() == pytest.approx(-23.5, abs=1e-3)
        emulator.unit = "W"  # by hand on the meter
        assert meter.read_power() == pytest.approx(-23.5, abs=1e-3)

    @pytest.mark.parametrize("watt", [0.0, -3.2e-11])
    def test_watts_at_or_below_zero_have_no_dbm(self, watt):
        """Noise near zero in W used to raise and stop the monitor."""
        emulator = NrxEmulator()
        emulator.unit, emulator.watt = "W", watt
        meter, _ = make(RohdeSchwarzNRX, emulator)
        assert math.isnan(meter.read_power())
        assert meter.fetch() == pytest.approx(watt)  # the reading itself is kept

    def test_options_configure_meter(self):
        emulator = NrxEmulator()
        meter, _ = make(RohdeSchwarzNRX, emulator, aperture_time=0.05, averaging=False)
        assert emulator.aperture == 0.05 and emulator.averaging is False
        meter.set_units("W")
        assert meter.read_power() == pytest.approx(-30.0, abs=1e-3)
        with pytest.raises(ConfigurationError):
            meter.set_units("V")

    def test_constructor_has_no_side_effects_by_default(self):
        _, link = make(RohdeSchwarzNRX, NrxEmulator())
        assert link.written == []

    def test_settings_are_configuration_quantities(self):
        from thzdaq_instruments.quantities import quantities_of, read_values
        from thzdaq_instruments.sim import SimPowerMeter

        emulator = NrxEmulator(power_dbm=-20.0)
        meter, _ = make(RohdeSchwarzNRX, emulator)
        quantities = {q.key: q for q in quantities_of(meter)}
        config = [k for k, q in quantities.items() if q.persistent]
        assert config == [
            "power_unit", "averaging", "filter_time", "aperture_time",
            "limit_lower", "limit_upper",
        ]  # fmt: skip
        for key, value in (
            ("power_unit", "W"), ("averaging", True), ("filter_time", 0.2),
            ("aperture_time", 0.1), ("limit_lower", -50.0), ("limit_upper", 10.0),
        ):  # fmt: skip
            quantities[key].write(meter, value)
            assert quantities[key].read(meter) == value
        values = read_values(meter)
        assert values["power"] == pytest.approx(-20.0, abs=1e-3)
        assert values["reading"] == pytest.approx(1e-5, rel=1e-3)  # W
        assert emulator.errors == []
        # The simulator has the same settings, so the dock is the same
        assert [q.key for q in quantities_of(SimPowerMeter())] == list(quantities)


class TestSisBlock:
    def test_offsets_are_applied(self):
        emulator = SisEmulator()
        block, link = make(
            ScontelSisBlock, emulator, offsets={"DEV4": (0.033e-3, -0.5e-6)}
        )
        bias = block.channel("DEV4")
        bias.set_voltage(2.5e-3)
        assert link.written[0] == f"BIAS:DEV4:VOLT {2.5e-3 - 0.033e-3}"
        reading = bias.measure()
        assert reading.voltage == pytest.approx(2.5e-3)
        assert reading.current == pytest.approx((2.5e-3 - 0.033e-3) / 20 - 0.5e-6)
        assert bias.get_voltage() == 2.5e-3

    def test_error_answers_are_retried(self):
        emulator = SisEmulator()
        block, _ = make(ScontelSisBlock, emulator)
        emulator.fail = 2
        block.channel("DEV2").set_voltage(1e-3)
        assert emulator.setpoints["DEV2"] == 1e-3

    def test_persistent_error_raises(self):
        emulator = SisEmulator()
        block, _ = make(ScontelSisBlock, emulator)
        emulator.fail = 3
        with pytest.raises(InstrumentResponseError):
            block.channel("DEV2").read_current()

    def test_precise_voltage_corrects_gain_and_offset(self):
        emulator = SisEmulator(gain=0.97, offset=0.02e-3)
        block, _ = make(ScontelSisBlock, emulator)
        bias = block.channel("DEV4")
        measured = bias.set_voltage_precise(2.6e-3, settle_time=0)
        assert measured == pytest.approx(2.6e-3, rel=1e-3)
        assert emulator.setpoints["DEV4"] != pytest.approx(2.6e-3, rel=1e-3)

    def test_precise_voltage_gives_up(self):
        emulator = SisEmulator(gain=0.0, offset=1e-3)
        block, _ = make(ScontelSisBlock, emulator)
        with pytest.raises(InstrumentError):
            block.channel("DEV4").set_voltage_precise(
                2.6e-3, settle_time=0, max_iterations=5
            )

    def test_ctrl_and_shorts(self):
        emulator = SisEmulator()
        block, _ = make(ScontelSisBlock, emulator)
        block.ctrl("DEV3").set_current(12.5e-3)
        assert block.ctrl("DEV3").get_current() == 12.5e-3
        block.channel("DEV4").set_short(False)
        assert block.channel("DEV4").get_short() is False
        assert block.test("DEV4")
        with pytest.raises(ConfigurationError):
            block.ctrl("DEV9")
        assert emulator.errors == []

    def test_write_calibration_to_eeprom(self):
        emulator = SisEmulator()
        block, link = make(ScontelSisBlock, emulator)
        coefficients = {"VoltageStep": 1e-05, "CurrentDAC": [-1322560, 32801.2]}
        assert block.channel("DEV4").write_calibration(coefficients) == "OK"
        assert emulator.eeprom["DEV4"] == coefficients
        assert (
            link.written[0].startswith("BIAS:DEV4:EEPR {")
            and " " not in link.written[0][15:]
        )

    def test_recommended_connection_reads_chunks(self):
        spec = ScontelSisBlock.connection()
        assert spec.read_termination is None and spec.read_delay == 0.05


class TestYig:
    def test_tune_uses_calibration(self):
        client = FakeJsonClient()
        yig = NiYigFilter(client=client)
        actual = yig.channel("yig_2").tune(6e9)
        code = client.requests[0][2]["value"]
        # Same code as the legacy frequency -> code calibration
        assert abs(code - round(4.05339694e-07 * 6e9 - 1.20514861e03)) <= 1
        assert client.requests[0][1] == "/devices/Dev1/write/yig_2/"
        assert actual == pytest.approx(2.46705639e06 * code + 2.97320263e09)
        assert abs(actual - 6e9) < 2.5e6

    def test_missing_result_is_response_error(self):
        class Broken(FakeJsonClient):
            def post(self, path, data=None):
                return {"detail": "busy"}

        with pytest.raises(InstrumentResponseError):
            NiYigFilter(client=Broken()).channel("yig_1").tune(6e9)

    def test_sim_has_same_shape(self):
        assert SimYigFilter.channel_keys == NiYigFilter.channel_keys


@contextmanager
def json_server(status=200, body=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def _reply(self):
            length = int(self.headers.get("Content-Length") or 0)
            payload = self.rfile.read(length) if length else b""
            requests.append((self.command, self.path, payload))
            data = json.dumps(body if body is not None else {"result": 7}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _reply

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], requests
    finally:
        server.shutdown()
        server.server_close()


class TestJsonHttpClient:
    def test_post_json(self):
        with json_server() as (port, requests):
            spec = ConnectionSpec(HTTP, host="127.0.0.1", port=port, timeout=2)
            yig = NiYigFilter(spec)
            frequency = yig.channel("yig_1").set_code(7)
            yig.close()
        assert frequency == pytest.approx(2.46705639e06 * 7 + 2.97320263e09)
        method, path, payload = requests[0]
        assert (method, path, json.loads(payload)) == (
            "POST",
            "/devices/Dev1/write/yig_1/",
            {"value": 7},
        )

    def test_http_error_status(self):
        with json_server(status=500, body={"error": "boom"}) as (port, _):
            client = JsonHttpClient(ConnectionSpec(HTTP, host="127.0.0.1", port=port))
            with pytest.raises(InstrumentResponseError):
                client.get("/")

    def test_refused(self):
        import socket

        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        client = JsonHttpClient(ConnectionSpec(HTTP, host="127.0.0.1", port=port))
        with pytest.raises(InstrumentConnectionError):
            client.get("/")

    def test_connect_and_read_timeouts(self, monkeypatch):
        import requests

        client = JsonHttpClient(ConnectionSpec(HTTP, host="127.0.0.1", port=1))
        for error, expected in (
            (requests.ConnectTimeout, InstrumentConnectionError),
            (requests.ReadTimeout, InstrumentTimeoutError),
        ):

            def fail(*args, **kwargs):
                raise error("simulated")

            monkeypatch.setattr(client._session, "request", fail)
            with pytest.raises(expected):
                client.get("/")


def make_chopper(**kwargs):
    registers = MotorRegisters(**kwargs)
    chopper = ModbusChopper(
        registers=registers, move_wait=0, align_wait=0, step_wait=0, align_steps=10
    )
    return chopper, registers


class TestChopper:
    def test_cold_to_hot_rotates_90_degrees(self):
        chopper, registers = make_chopper(physical=2500)
        assert chopper.read_sensors() == (False, False)
        chopper.to_hot()
        assert registers.sensors() == (True, True)
        assert registers.physical == 5000
        assert chopper.position() == 0  # origin reset at the hot position

    @pytest.mark.parametrize(
        "target, expected", [("to_hot", (True, True)), ("to_cold", (False, False))]
    )
    def test_half_way_blade_is_nudged(self, target, expected):
        chopper, registers = make_chopper(physical=1250)
        assert registers.sensors() == (True, False)
        getattr(chopper, target)()
        assert registers.sensors() == expected

    def test_already_there_does_not_move(self):
        chopper, registers = make_chopper(physical=0)
        chopper.to_hot()
        assert registers.physical == 0
        triggers = [w for w in registers.writes if w[0] == chopper_module.REG_CONTROL]
        assert triggers == [
            (chopper_module.REG_CONTROL, chopper_module.CTRL_SET_ORIGIN)
        ]

    def test_stuck_blade_raises(self):
        chopper, _ = make_chopper(physical=2500, stuck=True)
        with pytest.raises(InstrumentError):
            chopper.to_hot()

    def test_rotate_aligns_to_detent_first(self):
        chopper, registers = make_chopper(physical=2600)
        chopper.rotate(90)
        assert registers.physical == 5000

    def test_go_to_negative_position(self):
        chopper, registers = make_chopper()
        chopper.go_to_position(-2500)
        assert chopper.position() == -2500

    def test_rotation_limits(self):
        chopper, _ = make_chopper()
        with pytest.raises(ConfigurationError):
            chopper.rotate(0)

    def test_int32_registers_roundtrip(self):
        for value in (0, 1, -1, 2500, -2500, 2**31 - 1, -(2**31)):
            assert registers_to_int32(int32_to_registers(value)) == value

    def test_unreachable_modbus_server(self):
        import socket

        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        spec = ConnectionSpec(MODBUS_TCP, host="127.0.0.1", port=port, timeout=0.5)
        with pytest.raises(InstrumentConnectionError):
            PymodbusRegisters(spec)


class TestDefaultRegistry:
    def test_drivers_are_registered_with_simulators(self):
        registry = default_registry()
        sources = {info.key for info in registry.find(VoltageSource)}
        assert {
            "rigol.dp832a",
            "rs.hmp2030",
            "keithley.2200",
            "scontel.sis_block",
        } <= sources
        assert {i.key for i in registry.find(PowerDetector)} == {
            "rs.nrx",
            "sim.power_meter",
        }
        supply = registry.open("rigol.dp832a", simulate=True)
        assert isinstance(supply, SimPowerSupply)

    def test_open_scpi_driver_through_pool(self):
        emulator = RigolEmulator()
        from thzdaq_instruments.transport.fake import FakeLink

        pool = TransportPool(lambda spec: FakeLink(emulator))
        supply = default_registry().open(
            "rigol.dp832a", RigolDP832A.connection(), pool=pool, name="IF switch"
        )
        supply.channel(2).set_output(True)
        assert emulator.channels[2].output
        supply.close()
        assert pool.open_links == 0

    def test_open_non_message_driver_gets_connection(self):
        yig = default_registry().open(
            "ni.yig", NiYigFilter.connection("10.0.0.9"), client=FakeJsonClient()
        )
        assert yig.channel("yig_1").tune(5e9) == pytest.approx(5e9, abs=2.5e6)

    def test_pool_refuses_non_message_connections(self):
        with pytest.raises(ConfigurationError):
            TransportPool().acquire(ModbusChopper.connection())


def closed_port() -> int:
    import socket

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class TestIdentifyAsksTheDevice:
    """Connect shows OK only after the device answered: identify() talks to it."""

    @pytest.mark.parametrize(
        "make_driver",
        [
            lambda spec: NiYigFilter(spec),
            lambda spec: ArduinoGrid(spec),
            lambda spec: SumitomoF70Rest(spec),
        ],
        ids=["yig", "grid", "f70_rest"],
    )
    def test_http_device_that_is_off(self, make_driver):
        spec = ConnectionSpec(HTTP, host="127.0.0.1", port=closed_port(), timeout=2)
        driver = make_driver(spec)  # nothing is sent when the driver is created
        with pytest.raises(InstrumentConnectionError):
            driver.identify()

    def test_http_device_answers(self):
        body = {"temperatures": [20, 20, 20, 20], "text": "OK"}
        with json_server(body=body) as (port, requests):
            spec = ConnectionSpec(HTTP, host="127.0.0.1", port=port, timeout=2)
            for driver in (NiYigFilter(spec), ArduinoGrid(spec), SumitomoF70Rest(spec)):
                assert driver.identify()
                driver.close()
        assert [(m, p) for m, p, _ in requests] == [
            ("GET", "/"),
            ("POST", "/test"),
            ("GET", "/api/v1/temperatures/"),
        ]

    def test_long_read_timeout_does_not_delay_a_device_that_is_off(self, monkeypatch):
        client = JsonHttpClient(ArduinoGrid.connection("127.0.0.1"))
        seen = []

        def request(*args, timeout, **kwargs):
            seen.append(timeout)
            raise RuntimeError("stop")

        monkeypatch.setattr(client._session, "request", request)
        with pytest.raises(RuntimeError):
            client.get("/")
        assert seen == [(3.0, 30.0)]

    def test_chopper_reads_the_drive(self):
        chopper, _ = make_chopper()
        assert chopper.identify()

        class Off(MotorRegisters):
            def read(self, address, count=1):
                raise InstrumentConnectionError("Modbus: no answer")

        with pytest.raises(InstrumentConnectionError):
            ModbusChopper(registers=Off()).identify()

    def test_f70_on_a_silent_serial_port(self):
        from emulators import F70Emulator

        compressor, _ = make(SumitomoF70, F70Emulator())
        assert "Sumitomo F-70" in compressor.identify()
        from thzdaq_instruments.transport.fake import fake_transport

        silent, _ = fake_transport()  # the port opened, nobody answers
        with pytest.raises(InstrumentTimeoutError):
            SumitomoF70(silent).identify()
