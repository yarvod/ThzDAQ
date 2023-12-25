from typing import Union

import settings
from api.adapters import PrologixManager
from store.deviceConfig import DeviceManager, DeviceConfig, DeviceConfigList


class KeithleyPowerSupplyManager(DeviceManager):
    name = "Keithley Power Supply"
    main_widget_class = "interface.views.KeithleyTabWidget"
    configs = DeviceConfigList()


class AgilentSignalGeneratorConfig(DeviceConfig):
    def __init__(
        self,
        name: str,
        cid: int,
        adapter: str = None,
        host: str = None,
        port: Union[str, int] = None,
        gpib: int = None,
        status: str = settings.NOT_INITIALIZED,
    ):
        super().__init__(name, cid, adapter, host, port, gpib, status)
        self.thread_set_config = False


class AgilentSignalGeneratorManager(DeviceManager):
    name = "Agilent Signal Generator"
    main_widget_class = "interface.views.SignalGeneratorTabWidget"
    config_class = AgilentSignalGeneratorConfig
    configs = DeviceConfigList()


def restore_configs():
    PrologixManager.restore_config()
    KeithleyPowerSupplyManager.restore_config()
    AgilentSignalGeneratorManager.restore_config()
