"""The SIS block's own sweep of a bias voltage: binary frames beside its text
commands, as ControlUnit4_Software's server and module take them."""

import socket
import struct

import pytest
from emulators import SisEmulator
from thzdaq_instruments.capabilities import VoltageSweep
from thzdaq_instruments.drivers import ScontelSisBlock
from thzdaq_instruments.errors import ConfigurationError, InstrumentConnectionError
from thzdaq_instruments.transport import SocketLink
from thzdaq_instruments.transport.fake import FakeLink

OFFSETS = {"DEV4": (0.03e-3, -0.5e-6)}


def block(emulator=None, **options):
    emulator = emulator or SisEmulator()
    transport, link = emulator.transport()
    return ScontelSisBlock(transport, **options), emulator, link


def frame(address, command, data=b""):
    return bytes([address, command, len(data)]) + data


def test_a_bias_sweeps_by_itself():
    sis, _, _ = block()
    assert isinstance(sis.channel("DEV4"), VoltageSweep)


def test_the_frames_go_one_by_one_in_the_order_of_the_block():
    sis, emulator, link = block()
    points = list(sis.channel("DEV4").sweep_voltage(0.0, 2e-3, 0.5e-3, 0.002))
    params = struct.pack("<fffIB3x", 0.0, 2e-3, 0.5e-3, 2, 1)
    assert link.written_frames == [
        frame(4, 0x30, params),  # BS_SetSweepParams
        frame(0xFF, 4),  # the server's pipe mode on
        frame(4, 0x31),  # BS_StartSweep
        frame(4, 0x32),  # BS_StopSweep
        frame(0xFF, 5),  # pipe mode off
    ]
    assert len(points) == 5 and not emulator.pipe and emulator.errors == []
    # Each frame is sent alone: the server takes one read as one command
    kinds = [kind for kind, _ in link.events if kind in ("wb", "w")]
    assert kinds == ["w", "w", "wb", "wb", "wb", "wb", "wb", "w"]


def test_points_come_back_with_the_offsets_and_the_voltage_stays_at_stop():
    sis, emulator, link = block(offsets=OFFSETS)
    bias = sis.channel("DEV4")
    points = list(bias.sweep_voltage(1e-3, 3e-3, 1e-3, 0.001))
    start, stop, *_ = emulator.sweeps["DEV4"]
    assert (start, stop) == pytest.approx((1e-3 - 0.03e-3, 3e-3 - 0.03e-3))
    assert [p.voltage for p in points] == pytest.approx([1e-3, 2e-3, 3e-3])
    device = [v - 0.03e-3 for v in (1e-3, 2e-3, 3e-3)]
    assert [p.current for p in points] == pytest.approx(
        [v / 20 - 0.5e-6 for v in device]
    )
    assert link.written[0] == "BIAS:DEV4:MODE?"
    assert link.written[1] == f"BIAS:DEV4:VOLT {1e-3 - 0.03e-3}"
    assert link.written[-1] == f"BIAS:DEV4:VOLT {3e-3 - 0.03e-3}"
    assert bias.get_voltage() == 3e-3


def test_a_sweep_closed_after_its_first_point_still_stops_and_leaves_pipe_mode():
    sis, emulator, link = block()
    bias = sis.channel("DEV4")
    sweep = bias.sweep_voltage(0.0, 5e-3, 0.5e-3, 0.001)
    next(sweep)
    sweep.close()
    assert link.written_frames[-2:] == [frame(4, 0x32), frame(0xFF, 5)]
    assert not emulator.pipe and emulator.sweeping == []
    # Where it stopped nobody knows: the setpoint is read
    assert bias.get_voltage() == pytest.approx(emulator.actual("DEV4"))
    assert link.written[-1] == "BIAS:DEV4:VOLT?"


def test_frames_of_anything_else_in_the_stream_are_passed_over():
    emulator = SisEmulator()
    other = struct.pack("<ffI", 1.0, 1.0, 0)
    emulator.slipped = frame(2, 0x33, other) + frame(4, 0x17, b"\x01")
    sis, _, _ = block(emulator)
    points = list(sis.channel("DEV4").sweep_voltage(0.0, 1e-3, 0.5e-3, 0.001))
    assert [p.voltage for p in points] == pytest.approx([0.0, 0.5e-3, 1e-3])


def test_a_current_biased_device_sweeps_in_voltage_and_goes_back():
    emulator = SisEmulator()
    emulator.modes["DEV4"] = "I"
    sis, _, link = block(emulator)
    list(sis.channel("DEV4").sweep_voltage(0.0, 1e-3, 0.5e-3, 0.001))
    assert "BIAS:DEV4:MODE U" in link.written
    assert link.written[-1] == "BIAS:DEV4:MODE I" and emulator.modes["DEV4"] == "I"


@pytest.mark.parametrize("dwell", [0.0004, 0.0, 1.5])
def test_a_dwell_the_block_or_the_link_cannot_keep_is_refused(dwell):
    sis, _, link = block()
    with pytest.raises(ConfigurationError, match="at a point"):
        sis.channel("DEV4").sweep_voltage(0.0, 1e-3, 0.5e-3, dwell)
    assert link.events == []


def test_text_commands_work_after_a_sweep():
    sis, emulator, _ = block()
    bias = sis.channel("DEV4")
    list(bias.sweep_voltage(0.0, 1e-3, 0.5e-3, 0.001))
    bias.set_voltage(2e-3)
    assert bias.read_voltage() == pytest.approx(2e-3)
    assert emulator.errors == []


def test_a_link_without_frames_refuses_them():
    link = FakeLink()
    with pytest.raises(InstrumentConnectionError, match="no frames"):
        link.write_bytes(b"\x04\x31\x00")


def test_a_socket_reads_frames_by_count_and_the_text_after_them():
    """The block's server sends a frame and a text answer as they come: what a
    frame read leaves is the start of the next text chunk."""
    server = socket.create_server(("127.0.0.1", 0))
    link = SocketLink(
        "127.0.0.1", server.getsockname()[1], timeout=2, read_termination=None
    )
    link.open()
    peer, _ = server.accept()
    with server, peer:
        link.write_bytes(frame(0xFF, 4))
        assert peer.recv(16) == frame(0xFF, 4)
        peer.sendall(frame(0xFF, 4) + frame(4, 0x33, b"\x00" * 4) + b"OK\r\n")
        assert link.read_bytes(3) == frame(0xFF, 4)
        assert link.read_bytes(7) == frame(4, 0x33, b"\x00" * 4)
        assert link.read_line() == "OK"
    link.close()
