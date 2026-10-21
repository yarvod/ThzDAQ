"""ThzDAQ instrument layer: capabilities, transports, drivers and simulators."""

from thzdaq_instruments.errors import (
    ConfigurationError,
    InstrumentConnectionError,
    InstrumentError,
    InstrumentResponseError,
    InstrumentTimeoutError,
    UnknownDriverError,
)
from thzdaq_instruments.instrument import Channel, Instrument, ScpiInstrument
from thzdaq_instruments.readings import ChannelReading
from thzdaq_instruments.registry import DriverInfo, DriverRegistry, default_registry
from thzdaq_instruments.transport import ConnectionSpec, TransportPool, default_pool

__all__ = [
    "Channel",
    "ChannelReading",
    "ConfigurationError",
    "ConnectionSpec",
    "DriverInfo",
    "DriverRegistry",
    "Instrument",
    "InstrumentConnectionError",
    "InstrumentError",
    "InstrumentResponseError",
    "InstrumentTimeoutError",
    "ScpiInstrument",
    "TransportPool",
    "UnknownDriverError",
    "default_pool",
    "default_registry",
]
