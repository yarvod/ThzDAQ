"""Shared links recover from timeouts, dead peers and hung reads."""

import socket
import threading
import time

import pytest
from thzdaq_instruments.errors import InstrumentConnectionError, InstrumentTimeoutError
from thzdaq_instruments.transport import SOCKET, ConnectionSpec, TransportPool
from thzdaq_instruments.transport.base import PROLOGIX
from thzdaq_instruments.transport.fake import FakeLink, fake_transport
from thzdaq_instruments.transport.links import SocketLink


def test_a_late_answer_is_not_read_as_the_next_one():
    transport, link = fake_transport({"B?": "b"})
    with pytest.raises(InstrumentTimeoutError):
        transport.query("A?")  # no answer in time
    link._replies.append("late a")  # ... it arrives later
    assert link.broken
    assert transport.query("B?") == "b"  # reconnected first: "late a" is gone
    assert link.open_count == 2 and not link.broken


def test_prologix_is_set_up_again_after_a_reconnect():
    links = []

    def factory(spec):
        link = FakeLink(lambda line: "ok" if line == "*IDN?" else None)
        links.append(link)
        return link

    pool = TransportPool(factory)
    spec = ConnectionSpec(PROLOGIX, host="h", gpib=19)
    gen = pool.acquire(spec)
    assert gen.query("*IDN?") == "ok"
    link = links[0]
    link.broken = True  # e.g. a timeout of another instrument on the bus
    assert gen.query("*IDN?") == "ok"
    assert link.written.count("++mode 1") == 2 and link.written.count("++addr 19") == 2


def test_pool_status_reset_and_abort():
    pool = TransportPool(lambda spec: FakeLink({"*IDN?": "x"}))
    spec = ConnectionSpec(SOCKET, host="10.0.0.30", port=5025)
    a, b = pool.acquire(spec), pool.acquire(spec)
    (status,) = pool.links()
    assert status.users == 2 and status.open and not status.broken
    assert pool.abort(spec.link_key) and pool.links()[0].broken
    assert a.query("*IDN?") == "x" and not pool.links()[0].broken
    assert pool.reset(spec.link_key) and b.query("*IDN?") == "x"
    assert not pool.reset(("tcp", "nowhere", 1))


def test_a_closed_transport_does_not_break_the_shared_link():
    pool = TransportPool(lambda spec: FakeLink({"*IDN?": "x"}))
    spec = ConnectionSpec(SOCKET, host="h", port=1)
    a, b = pool.acquire(spec), pool.acquire(spec)
    a.close()
    with pytest.raises(InstrumentConnectionError):
        a.query("*IDN?")
    assert not pool.links()[0].broken and b.query("*IDN?") == "x"


@pytest.mark.parametrize("platform", ["here", "win32"])
def test_abort_wakes_a_read_blocked_on_a_silent_device(platform, monkeypatch):
    if platform == "win32":  # the Windows path (close after shutdown) runs too
        monkeypatch.setattr("thzdaq_instruments.transport.links.sys.platform", "win32")
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    link = SocketLink("127.0.0.1", port, timeout=10)
    link.open()
    peer, _ = server.accept()  # accepts, never answers
    errors = []

    def read():
        try:
            link.read_line()
        except (InstrumentConnectionError, InstrumentTimeoutError) as e:
            errors.append(e)

    thread = threading.Thread(target=read)
    started = time.monotonic()
    thread.start()
    time.sleep(0.2)
    link.abort()
    thread.join(5)
    assert errors and time.monotonic() - started < 3  # not the 10 s timeout
    assert link.broken
    link.reset()  # reconnects after the abort, on every platform
    peer.close()
    peer, _ = server.accept()
    peer.sendall(b"OK\n")
    assert link.read_line() == "OK"
    link.close()
    peer.close()
    server.close()


def test_serial_reconnect_drops_a_late_answer(monkeypatch):
    import serial

    opened = []

    class Port:
        def __init__(self, **kwargs):
            self.buffer = b"late answer\n"  # left from before the reconnect
            opened.append(self)

        def reset_input_buffer(self):
            self.buffer = b""

        def close(self):
            pass

    monkeypatch.setattr(serial, "Serial", Port)
    from thzdaq_instruments.transport.links import SerialLink

    link = SerialLink("/dev/ttyUSB0")
    link.open()
    link.reset()
    assert len(opened) == 2 and all(port.buffer == b"" for port in opened)


def tcp_links(responses):
    links = []

    def factory(spec):
        link = FakeLink(responses)
        link.idle_closable = True  # a TCP socket
        links.append(link)
        return link

    return links, factory


def test_unused_connection_is_closed_and_reopened_on_use():
    links, factory = tcp_links({"FETCH?": "-30.0"})
    pool = TransportPool(factory)
    meter = pool.acquire(ConnectionSpec(SOCKET, host="nrx", port=5025))
    assert meter.query("FETCH?") == "-30.0"
    link = links[0]
    assert pool.close_idle(5.0) == []  # just used
    link.last_used -= 10
    assert pool.close_idle(5.0) == [("tcp", "nrx", 5025)]
    assert not link.is_open and link.idle and not link.broken
    assert meter.query("FETCH?") == "-30.0"  # reopened, nothing lost
    assert link.open_count == 2 and link.is_open and not link.idle


def test_idle_prologix_is_set_up_again_and_busy_links_stay():
    links, factory = tcp_links(lambda line: "ok" if line == "*IDN?" else None)
    pool = TransportPool(factory)
    gen = pool.acquire(ConnectionSpec(PROLOGIX, host="h", gpib=19))
    gen.query("*IDN?")
    link = links[0]
    link.last_used -= 10
    with link.lock:  # a command in progress in another thread
        held = threading.Thread(target=lambda: closed.extend(pool.close_idle(5.0)))
        closed = []
        held.start()
        held.join()
    assert closed == [] and link.is_open
    assert pool.close_idle(5.0) and not link.is_open
    assert gen.query("*IDN?") == "ok"
    assert link.written.count("++mode 1") == 2 and link.written.count("++addr 19") == 2


def test_serial_links_are_never_closed_for_idling():
    pool = TransportPool(lambda spec: FakeLink({"*IDN?": "x"}))  # not idle_closable
    pool.acquire(ConnectionSpec(SOCKET, host="h", port=1)).query("*IDN?")
    (status,) = pool.links()
    pool._entries[status.key].link.last_used -= 100
    assert pool.close_idle(5.0) == [] and pool.links()[0].open


def test_instrument_sees_the_idle_client_leave():
    """The NRX stayed in remote after a monitor: the socket was never closed."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(2)
    port = server.getsockname()[1]
    pool = TransportPool()
    meter = pool.acquire(ConnectionSpec(SOCKET, host="127.0.0.1", port=port))
    peer, _ = server.accept()
    meter.write("SYST:BEEP")
    assert peer.recv(64) == b"SYST:BEEP\n"
    next(iter(pool._entries.values())).link.last_used -= 10
    assert pool.close_idle(5.0)
    peer.settimeout(2)
    assert peer.recv(64) == b""  # the client is gone: the instrument goes local
    meter.write("*CLS")  # the next command connects again
    again, _ = server.accept()
    assert again.recv(64) == b"*CLS\n"
    meter.close()
    for s in (peer, again, server):
        s.close()


def test_modbus_socket_reset_is_an_instrument_error():
    """pymodbus lets a reset socket (WinError 10054) through as a bare OSError."""
    from thzdaq_instruments.transport.modbus import PymodbusRegisters

    class Client:
        def read_holding_registers(self, *args, **kwargs):
            raise ConnectionResetError(10054, "the remote host closed the connection")

    registers = PymodbusRegisters.__new__(PymodbusRegisters)
    registers.client, registers.slave, registers.lock = Client(), 1, threading.RLock()
    with pytest.raises(InstrumentConnectionError):
        registers.read(0x10)
