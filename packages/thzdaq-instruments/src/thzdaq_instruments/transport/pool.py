import logging
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.transport.base import (
    PROLOGIX,
    SOCKET,
    ConnectionSpec,
    Link,
    MessageTransport,
    Transport,
)
from thzdaq_instruments.transport.links import SerialLink, SocketLink
from thzdaq_instruments.transport.prologix import PrologixController, PrologixTransport

logger = logging.getLogger(__name__)

LinkFactory = Callable[[ConnectionSpec], Link]


def default_link_factory(spec: ConnectionSpec) -> Link:
    if spec.kind in (SOCKET, PROLOGIX):
        return SocketLink(
            host=spec.host,
            port=spec.port,
            timeout=spec.timeout,
            write_termination=spec.write_termination,
            read_termination=spec.read_termination,
        )
    return SerialLink(
        port=spec.serial_port,
        baudrate=spec.baudrate,
        timeout=spec.timeout,
        write_termination=spec.write_termination,
        read_termination=spec.read_termination,
    )


@dataclass
class _Entry:
    link: Link
    prologix: bool
    controller: Optional[PrologixController]
    refs: int = 0


class TransportPool:
    """Hands out transports, sharing one physical link per endpoint.

    The link is opened on the first acquire and closed when the last transport
    on it is closed. The first spec for an endpoint defines link settings.
    """

    def __init__(self, link_factory: LinkFactory = default_link_factory):
        self._link_factory = link_factory
        self._lock = threading.Lock()
        self._entries: Dict[tuple, _Entry] = {}

    def acquire(self, spec: ConnectionSpec) -> Transport:
        key = spec.link_key
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                link = self._link_factory(spec)
                link.open()
                controller = (
                    PrologixController(link, spec.timeout) if spec.is_prologix else None
                )
                entry = _Entry(
                    link=link, prologix=spec.is_prologix, controller=controller
                )
                self._entries[key] = entry
                logger.info(f"[TransportPool] opened {link!r}")
            elif entry.prologix != spec.is_prologix:
                raise ConfigurationError(
                    f"{key} is already used as {'Prologix' if entry.prologix else 'direct'} link"
                )
            entry.refs += 1

        on_close = self._releaser(key)
        if entry.controller is not None:
            return PrologixTransport(
                entry.link,
                entry.controller,
                spec.gpib,
                read_delay=spec.read_delay,
                on_close=on_close,
            )
        return MessageTransport(
            entry.link, read_delay=spec.read_delay, on_close=on_close
        )

    def _releaser(self, key: tuple) -> Callable[[], None]:
        def release():
            with self._lock:
                entry = self._entries.get(key)
                if entry is None:
                    return
                entry.refs -= 1
                if entry.refs > 0:
                    return
                del self._entries[key]
            with entry.link.lock:
                entry.link.close()
            logger.info(f"[TransportPool] closed {entry.link!r}")

        return release

    def references(self, spec: ConnectionSpec) -> int:
        with self._lock:
            entry = self._entries.get(spec.link_key)
            return entry.refs if entry else 0

    @property
    def open_links(self) -> int:
        with self._lock:
            return len(self._entries)

    def close_all(self) -> None:
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            with entry.link.lock:
                entry.link.close()


default_pool = TransportPool()
