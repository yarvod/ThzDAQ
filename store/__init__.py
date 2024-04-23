from typing import Union

import settings
from store.adapterConfig import AdapterManager
from store.deviceConfig import (
    DeviceManager,
    DeviceConfig,
    DeviceConfigList,
    DeviceEventManager,
)


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
        config_manager=None,
    ):
        super().__init__(name, cid, adapter, host, port, gpib, status, config_manager)
        self.thread_set_config = False


class AgilentSignalGeneratorManager(DeviceManager):
    name = "Agilent Signal Generator"
    main_widget_class = "interface.views.SignalGeneratorTabWidget"
    config_class = AgilentSignalGeneratorConfig
    configs = DeviceConfigList()


class RigolPowerSupplyConfig(DeviceConfig):
    def __init__(
        self,
        name: str,
        cid: int,
        adapter: str = None,
        host: str = None,
        port: Union[str, int] = None,
        gpib: int = None,
        status: str = settings.NOT_INITIALIZED,
        config_manager=None,
    ):
        super().__init__(name, cid, adapter, host, port, gpib, status, config_manager)
        self.monitor_ch1 = True
        self.monitor_ch2 = True
        self.monitor_ch3 = True


class RigolPowerSupplyManager(DeviceManager):
    name = "Rigol Power Supply"
    main_widget_class = "interface.views.RigolPowerSupplyTabWidget"
    configs = DeviceConfigList()
    config_class = RigolPowerSupplyConfig


class SumitomoF70Manager(DeviceManager):
    name = "Sumitomo F70 Compressor"
    main_widget_class = "interface.views.SumitomoF70TabWidget"
    configs = DeviceConfigList()


class LakeShoreTemperatureControllerManager(DeviceManager):
    name = "LakeShore Temperature Controller"
    main_widget_class = "interface.views.TemperatureControllerTabWidget"
    configs = DeviceConfigList()


class RohdeSchwarzVnaZva67Manager(DeviceManager):
    name = "Rohde Schwarz VNA ZVA 67"
    main_widget_class = "interface.views.VNATabWidget"
    configs = DeviceConfigList()
    event_manager = DeviceEventManager()


class RohdeSchwarzSpectrumFsek30Config(DeviceConfig):
    def __init__(
        self,
        name: str,
        cid: int,
        adapter: str = None,
        host: str = None,
        port: Union[str, int] = None,
        gpib: int = None,
        status: str = settings.NOT_INITIALIZED,
        config_manager=None,
    ):
        super().__init__(name, cid, adapter, host, port, gpib, status, config_manager)
        self.start_frequency: float = None
        self.stop_frequency: float = None


class RohdeSchwarzSpectrumFsek30Manager(DeviceManager):
    name = "Rohde Schwarz Spectrum FSEK 30"
    main_widget_class = "interface.views.SpectrumTabWidget"
    config_class = RohdeSchwarzSpectrumFsek30Config
    configs = DeviceConfigList()
    event_manager = DeviceEventManager()


class PrologixManager(AdapterManager):
    name = "Prologix ethernet"


def restore_configs():
    PrologixManager.restore_config()
    KeithleyPowerSupplyManager.restore_config()
    AgilentSignalGeneratorManager.restore_config()
    RigolPowerSupplyManager.restore_config()
    SumitomoF70Manager.restore_config()
    LakeShoreTemperatureControllerManager.restore_config()
    RohdeSchwarzVnaZva67Manager.restore_config()
    RohdeSchwarzSpectrumFsek30Manager.restore_config()


def store_configs():
    KeithleyPowerSupplyManager.store_config()
    PrologixManager.store_config()
    AgilentSignalGeneratorManager.store_config()
    RigolPowerSupplyManager.store_config()
    SumitomoF70Manager.store_config()
    LakeShoreTemperatureControllerManager.store_config()
    RohdeSchwarzVnaZva67Manager.store_config()
    RohdeSchwarzSpectrumFsek30Manager.store_config()
