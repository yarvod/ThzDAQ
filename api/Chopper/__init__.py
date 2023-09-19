import logging

from api.Chopper.chopper_ethernet import ChopperEthernet
from api.Chopper.chopper_sync import Chopper
from settings import SERIAL_USB, WAVESHARE_ETHERNET


logger = logging.getLogger(__name__)


class ChopperManager:
    adapters_classes = {
        WAVESHARE_ETHERNET: ChopperEthernet,
        SERIAL_USB: Chopper,
    }
    adapters = {}
    adapter = WAVESHARE_ETHERNET

    def init_adapter(self, adapter: str = WAVESHARE_ETHERNET, *args, **kwargs):
        self.adapter = adapter
        _adapter = self.adapters_classes.get(adapter)
        _adapter = _adapter(*args, **kwargs)
        self.adapters[adapter] = _adapter
        return _adapter

    @property
    def chopper(self) -> Chopper:
        if not self.adapters.get(self.adapter):
            logger.warning(
                f"[{self.__class__.__name__}.chopper] adapter instance not found, creating default..."
            )
            self.init_adapter()
        if not self.adapters[self.adapter].client.connected:
            self.adapters[self.adapter].connect()
        return self.adapters[self.adapter]


chopper_manager = ChopperManager()
