"""Leases: which running measurement uses a device, and how.

Only exclusive use conflicts: setting a device another measurement sweeps,
starting a measurement that needs a device another sweeps, or one that sweeps
a device another uses (reading never conflicts). An explicit intent (share)
goes on, and the conflict is returned so both measurements record it.
"""

import threading
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from thzdaq_api.leases import EXCLUSIVE, READ


@dataclass(frozen=True)
class Lease:
    device: str
    mode: str  # read, shared, exclusive
    owner: int  # the measurement's number
    title: str  # of the measurement, for messages


class LeaseConflict(Exception):
    def __init__(self, leases: Tuple[Lease, ...]):
        self.leases = leases
        super().__init__(
            "; ".join(
                f"{lease.device} is used {lease.mode} by measurement "
                f"#{lease.owner} ({lease.title})"
                for lease in leases
            )
        )


def conflicts(mode: str, other: str) -> bool:
    return READ not in (mode, other) and EXCLUSIVE in (mode, other)


class Leases:
    def __init__(self):
        self._leases: Dict[int, Tuple[Lease, ...]] = {}
        self._lock = threading.Lock()

    def acquire(
        self, owner: int, title: str, modes: Mapping[str, str], share: bool
    ) -> Tuple[Lease, ...]:
        """Take the devices (device -> mode) for a measurement; returns the
        conflicts accepted with share, raises LeaseConflict without it."""
        with self._lock:
            clashes = tuple(
                lease
                for device, mode in modes.items()
                for lease in self._of(device)
                if lease.owner != owner and conflicts(mode, lease.mode)
            )
            if clashes and not share:
                raise LeaseConflict(clashes)
            self._leases[owner] = tuple(
                Lease(device, mode, owner, title) for device, mode in modes.items()
            )
            return clashes

    def release(self, owner: int) -> bool:
        with self._lock:
            return self._leases.pop(owner, None) is not None

    def of(self, device: str) -> List[Lease]:
        with self._lock:
            return self._of(device)

    def blocking(self, device: str, writer: Optional[int] = None) -> List[Lease]:
        """Leases a set of the device would conflict with (it is swept)."""
        return [
            lease
            for lease in self.of(device)
            if lease.owner != writer and lease.mode == EXCLUSIVE
        ]

    def all(self) -> List[Lease]:
        with self._lock:
            return [lease for leases in self._leases.values() for lease in leases]

    def _of(self, device: str) -> List[Lease]:
        return [
            lease
            for leases in self._leases.values()
            for lease in leases
            if lease.device == device
        ]
