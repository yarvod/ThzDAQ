class InstrumentError(Exception):
    """Base class for every instrument layer failure."""


class InstrumentConnectionError(InstrumentError):
    """Connection can't be opened or was lost."""


class InstrumentTimeoutError(InstrumentError):
    """Instrument didn't answer in time."""


class InstrumentResponseError(InstrumentError):
    """Instrument answered with an error or an unparsable value."""


class ConfigurationError(InstrumentError):
    """Invalid connection spec, channel or driver configuration."""


class UnknownDriverError(ConfigurationError):
    """Driver key is not registered."""
