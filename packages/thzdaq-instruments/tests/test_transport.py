import socket
import threading
from contextlib import contextmanager

import pytest
from thzdaq_instruments.errors import (
    ConfigurationError,
    InstrumentConnectionError,
    InstrumentTimeoutError,
)
from thzdaq_instruments.transport import (
    PROLOGIX,
    SERIAL,
    SOCKET,
    ConnectionSpec,
    SocketLink,
    TransportPool,
)
from thzdaq_instruments.transport.fake import FakeLink, fake_transport

PROLOGIX_SETUP = [
    "++mode 1",
    "++auto 0",
    "++read_tmo_ms 2000",
    "++eos 3",
    "++savecfg 0",
]


def echo(line: str):
    return f"echo {line}" if line.endswith("?") else None


class TestConnectionSpec:
    def test_prologix_gets_default_port(self):
        spec = ConnectionSpec(PROLOGIX, host="10.0.0.1", gpib=19)
        assert spec.port == 1234
        assert spec.link_key == ("tcp", "10.0.0.1", 1234)

    def test_gpib_devices_share_link_key(self):
        lo = ConnectionSpec(PROLOGIX, host="10.0.0.1", gpib=19)
        assert lo.with_gpib(18).link_key == lo.link_key

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"kind": "usb"},
            {"kind": SOCKET, "port": 5025},
            {"kind": SOCKET, "host": "10.0.0.1"},
            {"kind": SERIAL},
            {"kind": PROLOGIX, "host": "10.0.0.1"},
            {"kind": PROLOGIX, "host": "10.0.0.1", "gpib": 31},
            {"kind": SOCKET, "host": "10.0.0.1", "port": 1, "timeout": 0},
        ],
    )
    def test_invalid_specs(self, kwargs):
        with pytest.raises(ConfigurationError):
            ConnectionSpec(**kwargs)


class TestMessageTransport:
    def test_query_writes_and_reads(self):
        transport, link = fake_transport({"*IDN?": "RIGOL,DP832A"})
        assert transport.query("*IDN?") == "RIGOL,DP832A"
        transport.write(":OUTP CH1,ON")
        assert link.written == ["*IDN?", ":OUTP CH1,ON"]

    def test_missing_reply_is_timeout(self):
        transport, _ = fake_transport()
        with pytest.raises(InstrumentTimeoutError):
            transport.query("*IDN?")

    def test_closed_transport_refuses_commands(self):
        transport, _ = fake_transport(echo)
        transport.close()
        with pytest.raises(InstrumentConnectionError):
            transport.query("*IDN?")


class FakeLinks:
    """Link factory for the pool that remembers created links."""

    def __init__(self, responses=echo, delay=0.0):
        self.responses = responses
        self.delay = delay
        self.links = []

    def __call__(self, spec):
        link = FakeLink(self.responses, delay=self.delay)
        self.links.append(link)
        return link


class TestTransportPool:
    def test_links_are_shared_and_closed_by_last_user(self):
        links = FakeLinks()
        pool = TransportPool(links)
        spec = ConnectionSpec(SOCKET, host="10.0.0.2", port=5025)

        first = pool.acquire(spec)
        second = pool.acquire(spec)
        assert len(links.links) == 1 and pool.references(spec) == 2

        first.close()
        first.close()  # idempotent, must not release twice
        assert links.links[0].is_open and pool.references(spec) == 1

        second.close()
        assert not links.links[0].is_open
        assert pool.open_links == 0

    def test_different_endpoints_get_different_links(self):
        links = FakeLinks()
        pool = TransportPool(links)
        pool.acquire(ConnectionSpec(SOCKET, host="10.0.0.2", port=5025))
        pool.acquire(ConnectionSpec(SOCKET, host="10.0.0.3", port=5025))
        assert pool.open_links == 2

    def test_prologix_setup_once_and_address_switching(self):
        links = FakeLinks()
        pool = TransportPool(links)
        lo = pool.acquire(ConnectionSpec(PROLOGIX, host="10.0.0.1", gpib=19))
        tone = pool.acquire(ConnectionSpec(PROLOGIX, host="10.0.0.1", gpib=18))

        assert lo.query("FREQ?") == "echo FREQ?"
        lo.write("OUTP 1")
        assert tone.query("FREQ?") == "echo FREQ?"

        link = links.links[0]
        assert len(links.links) == 1
        assert link.written == PROLOGIX_SETUP + [
            "++addr 19",
            "FREQ?",
            "++read eoi",
            "OUTP 1",
            "++addr 18",
            "FREQ?",
            "++read eoi",
        ]

    def test_direct_and_prologix_on_same_endpoint_conflict(self):
        pool = TransportPool(FakeLinks())
        pool.acquire(ConnectionSpec(PROLOGIX, host="10.0.0.1", gpib=19))
        with pytest.raises(ConfigurationError):
            pool.acquire(ConnectionSpec(SOCKET, host="10.0.0.1", port=1234))

    def test_concurrent_queries_do_not_interleave(self):
        links = FakeLinks(delay=0.001)
        pool = TransportPool(links)
        transports = [
            pool.acquire(ConnectionSpec(PROLOGIX, host="10.0.0.1", gpib=address))
            for address in (18, 19, 20)
        ]
        errors = []

        def worker(transport, index):
            try:
                for n in range(20):
                    command = f"Q{index}-{n}?"
                    assert transport.query(command) == f"echo {command}"
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(transport, index))
            for index, transport in enumerate(transports)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []

        # Every query is "++addr?" + command + "++read eoi" + reply, never mixed
        events = [e for e in links.links[0].events if e[1] not in PROLOGIX_SETUP]
        for index, (kind, line) in enumerate(events):
            if kind == "w" and line.startswith("Q"):
                assert events[index + 1] == ("w", "++read eoi")
                assert events[index + 2] == ("r", f"echo {line}")

    def test_failed_open_is_not_cached(self):
        class FailingLink(FakeLink):
            def open(self):
                raise InstrumentConnectionError("refused")

        pool = TransportPool(lambda spec: FailingLink())
        spec = ConnectionSpec(SOCKET, host="10.0.0.2", port=5025)
        with pytest.raises(InstrumentConnectionError):
            pool.acquire(spec)
        assert pool.open_links == 0


@contextmanager
def scpi_server(handler):
    """Local TCP server: handler(connection) runs for the first client."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve():
        try:
            connection, _ = server.accept()
        except OSError:
            return
        with connection:
            handler(connection)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.close()
        thread.join(timeout=2)


class TestSocketLink:
    def test_reply_split_across_packets(self):
        def handler(connection):
            connection.recv(1024)
            connection.sendall(b"RIGOL TECHNOLOGIES,")
            connection.sendall(b"DP832A\r\n0.5\n")
            connection.recv(1024)

        with scpi_server(handler) as port:
            link = SocketLink("127.0.0.1", port, timeout=1)
            link.open()
            link.write_line("*IDN?")
            assert link.read_line() == "RIGOL TECHNOLOGIES,DP832A"
            assert link.read_line() == "0.5"
            link.close()

    def test_unterminated_device_in_legacy_mode(self):
        def handler(connection):
            connection.recv(1024)
            connection.sendall(b"OK")
            connection.recv(1024)

        with scpi_server(handler) as port:
            link = SocketLink("127.0.0.1", port, timeout=1, read_termination=None)
            link.open()
            link.write_line("BIAS:DEV4:VOLT 0.001")
            assert link.read_line() == "OK"
            link.close()

    def test_silent_device_times_out(self):
        def handler(connection):
            connection.recv(1024)
            connection.recv(1024)

        with scpi_server(handler) as port:
            link = SocketLink("127.0.0.1", port, timeout=0.2)
            link.open()
            link.write_line("*IDN?")
            with pytest.raises(InstrumentTimeoutError):
                link.read_line()
            link.close()

    def test_peer_close_is_connection_error(self):
        def handler(connection):
            connection.recv(1024)

        with scpi_server(handler) as port:
            link = SocketLink("127.0.0.1", port, timeout=1)
            link.open()
            link.write_line("*IDN?")
            with pytest.raises(InstrumentConnectionError):
                link.read_line()
            link.close()

    def test_refused_connection(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        with pytest.raises(InstrumentConnectionError):
            SocketLink("127.0.0.1", port, timeout=0.5).open()
