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
        self.output_ch1 = False
        self.output_ch2 = False
        self.output_ch3 = False


class RigolPowerSupplyManager(DeviceManager):
    name = "Rigol Power Supply"
    main_widget_class = "interface.views.RigolPowerSupplyTabWidget"
    configs = DeviceConfigList()
    config_class = RigolPowerSupplyConfig


class SumitomoF70Config(DeviceConfig):
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
        self.thread_stream = False


class SumitomoF70Manager(DeviceManager):
    name = "Sumitomo F70 Compressor"
    main_widget_class = "interface.views.SumitomoF70TabWidget"
    configs = DeviceConfigList()
    config_class = SumitomoF70Config


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


def restore_configs(qsettings):
    PrologixManager.restore_config(qsettings)
    KeithleyPowerSupplyManager.restore_config(qsettings)
    AgilentSignalGeneratorManager.restore_config(qsettings)
    RigolPowerSupplyManager.restore_config(qsettings)
    SumitomoF70Manager.restore_config(qsettings)
    LakeShoreTemperatureControllerManager.restore_config(qsettings)
    RohdeSchwarzVnaZva67Manager.restore_config(qsettings)
    RohdeSchwarzSpectrumFsek30Manager.restore_config(qsettings)


def store_configs(qsettings):
    KeithleyPowerSupplyManager.store_config(qsettings)
    PrologixManager.store_config(qsettings)
    AgilentSignalGeneratorManager.store_config(qsettings)
    RigolPowerSupplyManager.store_config(qsettings)
    SumitomoF70Manager.store_config(qsettings)
    LakeShoreTemperatureControllerManager.store_config(qsettings)
    RohdeSchwarzVnaZva67Manager.store_config(qsettings)
    RohdeSchwarzSpectrumFsek30Manager.store_config(qsettings)
