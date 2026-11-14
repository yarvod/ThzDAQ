"""Who uses a device now and how: the leases of running measurements.

read: only reads it; shared: sets it, others may too (a load, the LO);
exclusive: sweeps it, so another's change spoils its data. Only exclusive use
conflicts, and an explicit intent (share) goes on anyway; both measurements
record it.
"""

from typing import Tuple

import msgspec

from thzdaq_api.operation import Operation

READ = "read"
SHARED = "shared"
EXCLUSIVE = "exclusive"


class LeaseInfo(msgspec.Struct, frozen=True):
    device: str
    mode: str  # read, shared or exclusive
    run: int  # the measurement using it
    title: str  # of that measurement


class ListLeases(Operation[Tuple[LeaseInfo, ...]]):
    """Devices in use by running measurements and how: read (only reads),
    shared (sets it, others may too) or exclusive (sweeps it)."""
