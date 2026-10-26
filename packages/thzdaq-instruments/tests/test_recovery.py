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
