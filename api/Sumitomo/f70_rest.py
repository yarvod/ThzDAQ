import logging
from typing import Union, List, Dict

import settings
from utils.functions import import_class


logger = logging.getLogger(__name__)


class F70Rest:
    def __init__(
        self,
        host: str = "192.168.129.106",
        port: int = 21024,
        adapter: str = settings.HTTP,
        adapter_instance=None,
        *args,
        **kwargs,
    ):
        self.host = host
        self.port = port
        self.adapter_name = adapter
        self.adapter = adapter_instance

        if self.adapter is None:
            self._set_adapter(adapter, *args, **kwargs)

    def _set_adapter(self, adapter: str, *args, **kwargs) -> None:
        adapter_path = settings.ADAPTERS.get(adapter)
        try:
            adapter_class = import_class(adapter_path)
            self.adapter = adapter_class(
                host=self.host, port=self.port, *args, **kwargs
            )
        except (ImportError, ImportWarning) as e:
            logger.error(f"[{self.__class__.__name__}._set_adapter] {e}")

    def test(self) -> bool:
        return bool(self.get_temperatures())

    def get_temperatures(self) -> Dict[str, List]:
        status, data = self.adapter.get(url="/api/v1/temperatures/")
        return data

    def get_pressures(self) -> Dict[str, List]:
        status, data = self.adapter.get(url="/api/v1/pressures/")
        return data

    def turn_on(self) -> Union[None, str]:
        status, data = self.adapter.post(url="/api/v1/turn-on/")
        return data

    def turn_off(self) -> Union[None, str]:
        status, data = self.adapter.post(url="/api/v1/turn-off/")
        return data


if __name__ == "__main__":
    c = F70Rest()
    print(c.get_temperatures())
    print(c.get_pressures())
