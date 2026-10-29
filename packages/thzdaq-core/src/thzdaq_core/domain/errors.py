from thzdaq_instruments.errors import ConfigurationError


class StationError(ConfigurationError):
    """Invalid station profile or a role that can't be built."""


class ProcedureError(ValueError):
    """Invalid procedure parameters or definition."""
