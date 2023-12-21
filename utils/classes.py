import logging
from typing import Union

from settings import ADAPTERS
from utils.functions import import_class


logger = logging.getLogger(__name__)


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class PrologixMeta(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        host = kwargs.get("host", None)
        if not host:
            host = args[0]  # FIXME: improve later
        if host not in cls._instances:
            cls._instances[host] = super(PrologixMeta, cls).__call__(*args, **kwargs)
        return cls._instances[host]


class BaseInstrument:
    def __init__(
        self,
        host: str,
        gpib: int,
        adapter: str,
        adapter_instance: "InstrumentAdapterInterface" = None,
        *args,
        **kwargs,
    ):
        self.host = host
        self.gpib = gpib
        self.adapter_name = adapter
        self.adapter: Union["InstrumentAdapterInterface", None] = adapter_instance

        if self.adapter is None:
            self._set_adapter(adapter, *args, **kwargs)

    def _set_adapter(self, adapter: str, *args, **kwargs) -> None:
        adapter_path = ADAPTERS.get(adapter)
        try:
            adapter_class = import_class(adapter_path)
            self.adapter = adapter_class(host=self.host, *args, **kwargs)
        except (ImportError, ImportWarning) as e:
            logger.error(f"[{self.__class__.__name__}._set_adapter] {e}")

    def query(self, cmd: str) -> str:
        if self.gpib:
            return self.adapter.query(cmd, eq_addr=self.gpib)
        return self.adapter.query(cmd)

    def write(self, cmd: str) -> None:
        if self.gpib:
            return self.adapter.write(cmd, eq_addr=self.gpib)
        return self.adapter.write(cmd)


class BaseInstrumentInterface:
    """Base Instrument Api interface"""

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def __del__(self):
        raise NotImplementedError


class InstrumentAdapterInterface:
    """
    This is the base interface for Instrument adapter
    """

    def read(self, *args, **kwargs):
        raise NotImplementedError

    def query(self, *args, **kwargs):
        raise NotImplementedError

    def write(self, *args, **kwargs):
        raise NotImplementedError

    def connect(self, *args, **kwargs):
        raise NotImplementedError

    def close(self, *args, **kwargs):
        raise NotImplementedError
