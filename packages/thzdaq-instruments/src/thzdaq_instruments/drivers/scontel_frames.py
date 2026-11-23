"""Binary frames of the Scontel control unit, beside its text commands on the
same socket: [address][command][length][data], little-endian. Only what the SIS
bias's own sweep needs, which the text commands lack.

Names and layouts are those of ControlUnit4_Software: Libs/StarProtocol
(servercommands.h, star_prc_commands.h, star_prc_structs.h). Its server
(System/TcpIpServer) takes one read of the socket as one command, so a frame
goes alone and its reply is read before the next one is sent.
"""

import struct
from dataclasses import dataclass
from typing import Collection

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.transport.base import Transport

# servercommands.h: the server's own address and commands. In pipe mode it
# sends this client the frames of a sweep and takes commands from it alone
SERVER_ADDRESS = 0xFF
CMD_SERVER_PIPE_MODE_ON = 4
CMD_SERVER_PIPE_MODE_OFF = 5

# star_prc_commands.h, the commands of a SIS bias source (CU4BSM0)
BS_SET_SWEEP_PARAMS = 0x30
BS_START_SWEEP = 0x31
BS_STOP_SWEEP = 0x32
BS_SWEEP_DATA = 0x33
CU4BSM0_UMODE = 1  # star_prc_structs.h: a sweep of the voltage

HEADER = struct.Struct("<BBB")
# CU4BSM0_SWEEP_PARAMS_t {float start, stop, step; unsigned timeStep_ms; char
# mode} as its client sends it: sizeof, padding included, 20 bytes. Whether the
# module's firmware takes 20 or 17 is a bench check (docs/workplan.md, stage 4)
SWEEP_PARAMS = struct.Struct("<fffIB3x")
# CU4BSM0_SWEEP_DATA_t {float current, voltage; unsigned time}
SWEEP_POINT = struct.Struct("<ffI")
SWEEP_END_LENGTH = 4  # the module ends a sweep with a sweep data frame this long


@dataclass(frozen=True)
class Frame:
    address: int
    command: int
    data: bytes = b""

    def encode(self) -> bytes:
        return HEADER.pack(self.address, self.command, len(self.data)) + self.data


def sweep_params(start: float, stop: float, step: float, dwell_ms: int) -> bytes:
    """V, V, V, ms: a sweep of the voltage."""
    return SWEEP_PARAMS.pack(start, stop, step, dwell_ms, CU4BSM0_UMODE)


def read_frame(transport: Transport) -> Frame:
    address, command, length = HEADER.unpack(transport.read_bytes(HEADER.size))
    return Frame(address, command, transport.read_bytes(length))


def exchange(transport: Transport, frame: Frame, skip: Collection[int] = ()) -> Frame:
    """Send a frame and read its reply: the frame of the same address and
    command. Frames of the commands in skip (a sweep's points still on their
    way) are passed over; any other is an error."""
    transport.write_bytes(frame.encode())
    while True:
        reply = read_frame(transport)
        if (reply.address, reply.command) == (frame.address, frame.command):
            return reply
        if reply.command not in skip:
            raise InstrumentResponseError(
                f"command {frame.command:#04x} to {frame.address} was answered"
                f" by {reply.command:#04x} from {reply.address}"
            )
