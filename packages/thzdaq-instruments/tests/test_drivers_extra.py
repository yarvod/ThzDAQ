import sys
import types

import pytest
from emulators import (
    F70Emulator,
    FakeJsonClient,
    FsekEmulator,
    LakeShoreEmulator,
    PfeifferBus,
    Sr830Emulator,
    ZvaEmulator,
)
from thzdaq_instruments.drivers import (
    ArduinoGrid,
    LakeShore336,
    PfeifferGauge,
    PfeifferTurboPump,
    RohdeSchwarzFSEK30,
    RohdeSchwarzZVA67,
    StanfordSR830,
    SumitomoF70,
    SumitomoF70Rest,
)
from thzdaq_instruments.drivers.lakeshore import HeaterSetup, OutputMode
from thzdaq_instruments.drivers.pfeiffer import (
    decode,
    encode,
    parse_telegram,
    read_telegram,
    write_telegram,
)
from thzdaq_instruments.drivers.rohde_schwarz.fsek import nearest_bandwidth
from thzdaq_instruments.drivers.sumitomo import F70Status, crc16_modbus
from thzdaq_instruments.errors import (
    ConfigurationError,
    InstrumentConnectionError,
    InstrumentResponseError,
    InstrumentTimeoutError,
)
from thzdaq_instruments.transport import (
    PROLOGIX_USB,
    VISA,
    ConnectionSpec,
    TransportPool,
)
from thzdaq_instruments.transport.fake import FakeLink, fake_transport
from thzdaq_instruments.units import PSI


def make(cls, emulator, **options):
    transport, link = emulator.transport()
    return cls(transport, **options), link


class TestZva:
    def test_waits_for_first_sweep(self):
        emulator = ZvaEmulator(zeros_before=2)
        vna, _ = make(RohdeSchwarzZVA67, emulator)
        trace = vna.read_trace(retry_delay=0)
        assert trace.parameter == "S11"
        assert trace.values[3] == pytest.approx(complex(0.3, -0.15))
        assert trace.frequency[1] == pytest.approx(3e9)

    def test_gives_up_on_empty_traces(self):
        vna, _ = make(RohdeSchwarzZVA67, ZvaEmulator(zeros_before=10))
        with pytest.raises(InstrumentResponseError):
            vna.read_trace(attempts=3, retry_delay=0)

    def test_parameter_definition(self):
        emulator = ZvaEmulator()
        vna, _ = make(RohdeSchwarzZVA67, emulator)
        vna.define_parameter("S21", "Trc2")
        assert vna.parameter_catalog() == {"Trc2": "S21"}
        vna.set_averaging(10)
        vna.set_averaging(1)
        vna.select_parameter("S12")
        assert vna.parameter_catalog() == {"Trc1": "S12"}
        assert emulator.data_format == "COMP"
        assert vna.test()
        assert emulator.errors == []


class TestFsek:
    def test_bandwidth_snaps_to_supported_values(self):
        assert nearest_bandwidth(180e3) == 200e3
        assert nearest_bandwidth(25e3) == 20e3
        emulator = FsekEmulator()
        analyzer, _ = make(RohdeSchwarzFSEK30, emulator)
        analyzer.set_resolution_bandwidth(180e3)
        analyzer.set_video_bandwidth(25e3)
        assert (emulator.rbw, emulator.vbw) == (200e3, 20e3)

    def test_video_bandwidth_auto_is_a_write(self):
        emulator = FsekEmulator()
        analyzer, link = make(RohdeSchwarzFSEK30, emulator)
        analyzer.set_video_bandwidth_auto(True)
        assert link.events == [("w", ":BAND:VID:AUTO ON")]

    def test_peak_and_trace(self):
        analyzer, _ = make(RohdeSchwarzFSEK30, FsekEmulator(tone=5.0001e9, level=-42.5))
        assert analyzer.read_peak() == (5.0001e9, -42.5)
        trace = analyzer.read_trace()
        assert trace.values == (-90.0, -80.0, -42.5, -90.0)
        assert trace.frequency[0] == pytest.approx(5e9 - 0.5e6)

    def test_sweep_mode(self):
        analyzer, _ = make(RohdeSchwarzFSEK30, FsekEmulator())
        analyzer.set_continuous_sweep(False)
        assert analyzer.get_continuous_sweep() is False


class TestLakeShore:
    def test_inputs_and_heater(self):
        emulator = LakeShoreEmulator()
        controller, _ = make(LakeShore336, emulator)
        assert controller.channel("A").read_temperature() == pytest.approx(4.215)
        heater = controller.heater(1)
        heater.set_setpoint(10.5)
        heater.set_range(2)
        heater.set_manual_output(25)
        assert heater.get_setpoint() == 10.5 and heater.get_range() == 2
        assert heater.get_manual_output() == 25 and heater.get_output() == 12.5
        assert heater.get_status() == 0
        assert controller.test()
        assert emulator.errors == []

    def test_setup_and_mode_roundtrip(self):
        controller, _ = make(LakeShore336, LakeShoreEmulator())
        heater = controller.heater(2)
        heater.setup(HeaterSetup(2, 0, 1.5, 2))
        assert heater.get_setup() == HeaterSetup(2, 0, 1.5, 2)
        heater.set_mode(OutputMode(1, 3, True))
        assert heater.get_mode() == OutputMode(1, 3, True)
        with pytest.raises(ConfigurationError):
            heater.set_mode(OutputMode(9, 1, False))
        with pytest.raises(ConfigurationError):
            controller.heater(5)


class TestSr830:
    def test_outputs(self):
        lockin, _ = make(StanfordSR830, Sr830Emulator())
        assert lockin.read("R") == pytest.approx(2.236e-3)
        assert lockin.read_xy() == (1e-3, -2e-3)

    def test_ranges_pick_supported_values(self):
        emulator = Sr830Emulator()
        lockin, _ = make(StanfordSR830, emulator)
        assert lockin.set_time_constant(0.25) == pytest.approx(0.3)
        assert emulator.state["OFLT"] == 9
        assert lockin.get_time_constant() == pytest.approx(0.3)
        assert lockin.set_sensitivity(3e-3) == pytest.approx(5e-3)
        assert lockin.get_sensitivity() == pytest.approx(5e-3)
        with pytest.raises(ConfigurationError):
            lockin.set_sensitivity(2)
        assert emulator.errors == []


class TestSumitomo:
    def test_crc_matches_manual(self):
        known = {"$TEA": "A4B9", "$PRA": "95F7", "$ON1": "77CF", "$OFF": "9188"}
        assert {cmd: crc16_modbus(cmd) for cmd in known} == known
        assert crc16_modbus("$STA") == "3504"

    def test_readings_in_si(self):
        emulator = F70Emulator()
        compressor, link = make(SumitomoF70, emulator)
        compressor.turn_on()
        assert compressor.read_temperatures()[0] == pytest.approx(68 + 273.15)
        assert compressor.read_pressures()[0] == pytest.approx(280 * PSI)
        status = compressor.read_status()
        assert status.system_on and status.solenoid_on and status.state == "local on"
        assert link.written[0] == "$ON177CF"
        assert emulator.errors == []

    def test_status_alarms(self):
        status = F70Status(0x0A81)  # cold head pause, pressure alarm, system on
        assert status.alarms == ("pressure",)
        assert status.state == "cold head pause"
        assert status.configuration == 1

    def test_bad_checksum_and_unknown_command(self):
        transport, _ = fake_transport(lambda line: "$TEA,068,034,032,000,FFFF")
        with pytest.raises(InstrumentResponseError):
            SumitomoF70(transport).read_temperatures()
        transport, _ = fake_transport(lambda line: "$???,3A5E")
        with pytest.raises(InstrumentResponseError):
            SumitomoF70(transport).turn_on()

    def test_connection_uses_carriage_return(self):
        spec = SumitomoF70.connection(serial_port="/dev/ttyUSB0")
        assert spec.write_termination == spec.read_termination == "\r"

    def test_rest_error_payload(self):
        class Broken(FakeJsonClient):
            def get(self, path):
                return {"error": "timeout"}

        with pytest.raises(InstrumentResponseError):
            SumitomoF70Rest(client=Broken()).read_temperatures()


class TestPfeiffer:
    @pytest.mark.parametrize(
        "data_type, raw, value",
        [
            (0, "111111", True),
            (6, "0", False),
            (1, "000820", 820),
            (2, "001571", 15.71),
            (7, "042", 42),
            (10, "100023", 1000.0),
            (10, "250017", 2.5e-3),
            (4, "TC 110", "TC 110"),
        ],
    )
    def test_codec_roundtrip(self, data_type, raw, value):
        assert decode(data_type, raw) == pytest.approx(value)
        assert encode(data_type, value) == raw

    def test_telegrams(self):
        assert read_telegram(1, 309) == "0010030902=?107"
        assert write_telegram(1, 10, "111111") == "0011001006111111015"
        assert parse_telegram("0011030906000820030", 1, 309) == "000820"
        with pytest.raises(InstrumentResponseError):
            parse_telegram("0011030906000820031", 1, 309)  # checksum
        with pytest.raises(InstrumentResponseError):
            parse_telegram("0021030906000820031", 1, 309)  # other address

    def make_bus(self):
        bus = PfeifferBus(
            {
                1: {309: "000820", 10: "000000", 303: "000000", 340: "150016"},
                2: {740: "250017"},
            }
        )
        pool = TransportPool(lambda spec: FakeLink(bus))
        spec = PfeifferTurboPump.connection(serial_port="/dev/ttyUSB1")
        return bus, pool, spec

    def test_pump_and_gauge_share_the_line(self):
        bus, pool, spec = self.make_bus()
        pump = PfeifferTurboPump(pool.acquire(spec), address=1)
        gauge = PfeifferGauge(pool.acquire(spec), address=2)
        assert pool.open_links == 1
        assert pump.actual_speed() == 820.0
        pump.set_pumping_station(True)
        assert bus.devices[1][10] == "111111"
        assert pump.read_pressure() == pytest.approx(1.5e-4 * 100)
        assert gauge.read_pressure() == pytest.approx(2.5e-3 * 100)
        assert pump.error_code() == "000000"
        assert bus.errors == []

    def test_undefined_and_read_only_parameters(self):
        _, pool, spec = self.make_bus()
        pump = PfeifferTurboPump(pool.acquire(spec), address=1)
        with pytest.raises(InstrumentResponseError):
            pump.get_parameter("TempMotor")
        with pytest.raises(ConfigurationError):
            pump.set_parameter("ActualSpd", 1)
        with pytest.raises(ConfigurationError):
            pump.get_parameter("ErrorAckn")
        with pytest.raises(ConfigurationError):
            PfeifferTurboPump(pool.acquire(spec), address=0)


class TestArduinoGrid:
    def test_http_rotation_is_relative(self):
        client = FakeJsonClient()
        grid = ArduinoGrid(client=client, angle=10)
        grid.rotate_to(45)
        grid.rotate_to(30)
        posts = [data for method, path, data in client.requests if path == "/rotate"]
        assert posts == [{"angle": 35}, {"angle": -15}]
        assert grid.get_angle() == 30

    def test_serial_rotation_is_absolute(self):
        transport, link = fake_transport({"test": "OK"})
        grid = ArduinoGrid(transport=transport)
        assert grid.test()
        grid.rotate_to(90)
        assert link.written[-1] == "90"


class FakeVisaError(Exception):
    def __init__(self, error_code):
        super().__init__(f"VISA error {error_code}")
        self.error_code = error_code


@pytest.fixture
def fake_pyvisa(monkeypatch):
    opened = []

    class Instrument:
        def __init__(self, resource):
            self.resource = resource
            self.replies = []
            self.written = []
            self.closed = False

        def write(self, line):
            self.written.append(line)
            if line == "*IDN?":
                self.replies.append("Keysight,82357B-test\n")

        def read(self):
            if not self.replies:
                raise FakeVisaError("timeout")
            return self.replies.pop(0)

        def close(self):
            self.closed = True

    class ResourceManager:
        def __init__(self, backend=""):
            pass

        def open_resource(self, resource):
            instrument = Instrument(resource)
            opened.append(instrument)
            return instrument

    module = types.ModuleType("pyvisa")
    module.ResourceManager = ResourceManager
    module.errors = types.SimpleNamespace(VisaIOError=FakeVisaError)
    module.constants = types.SimpleNamespace(
        StatusCode=types.SimpleNamespace(error_timeout="timeout")
    )
    monkeypatch.setitem(sys.modules, "pyvisa", module)
    return opened


class TestOtherGpibAdapters:
    def test_visa_resource(self, fake_pyvisa):
        pool = TransportPool()
        spec = ConnectionSpec(VISA, resource="GPIB0::19::INSTR", timeout=1.5)
        transport = pool.acquire(spec)
        assert transport.query("*IDN?") == "Keysight,82357B-test"
        instrument = fake_pyvisa[0]
        assert instrument.timeout == 1500 and instrument.write_termination == "\n"
        with pytest.raises(InstrumentTimeoutError):
            transport.query("FREQ?")
        transport.close()
        assert instrument.closed

    def test_visa_requires_resource_and_pyvisa(self, monkeypatch):
        with pytest.raises(ConfigurationError):
            ConnectionSpec(VISA)
        monkeypatch.setitem(sys.modules, "pyvisa", None)
        with pytest.raises(InstrumentConnectionError):
            TransportPool().acquire(ConnectionSpec(VISA, resource="GPIB0::1::INSTR"))

    def test_prologix_usb_shares_serial_port(self):
        links = []

        def factory(spec):
            link = FakeLink(lambda line: "ok" if line.endswith("?") else None)
            links.append(link)
            return link

        pool = TransportPool(factory)
        lo = pool.acquire(ConnectionSpec(PROLOGIX_USB, serial_port="COM5", gpib=19))
        spectrum = pool.acquire(
            ConnectionSpec(PROLOGIX_USB, serial_port="COM5", gpib=20)
        )
        lo.query("FREQ?")
        spectrum.query("CALC:MARK:Y?")
        assert len(links) == 1
        assert "++addr 19" in links[0].written and "++addr 20" in links[0].written


def test_json_client_accepts_plain_text():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from thzdaq_instruments.transport.http import JsonHttpClient

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = b"rotated"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        spec = ConnectionSpec("http", host="127.0.0.1", port=server.server_address[1])
        grid = ArduinoGrid(spec)
        assert grid.rotate_to(15) == 15
        assert JsonHttpClient(spec).post("/rotate", {"angle": 1}) == {"text": "rotated"}
    finally:
        server.shutdown()
        server.server_close()
