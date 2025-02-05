from typing import Union, Optional

from PyQt5.QtCore import pyqtProperty, pyqtSignal

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
        gpib: int = 0,
        status: str = settings.NOT_INITIALIZED,
        delay: float = 0,
        config_manager=None,
    ):
        super().__init__(
            name=name,
            cid=cid,
            adapter=adapter,
            host=host,
            port=port,
            gpib=gpib,
            status=status,
            delay=delay,
            config_manager=config_manager,
        )
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
        delay: float = 0,
        config_manager=None,
    ):
        super().__init__(
            name=name,
            cid=cid,
            adapter=adapter,
            host=host,
            port=port,
            gpib=gpib,
            status=status,
            delay=delay,
            config_manager=config_manager,
        )
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
        delay: float = 0,
        config_manager=None,
    ):
        super().__init__(
            name=name,
            cid=cid,
            adapter=adapter,
            host=host,
            port=port,
            gpib=gpib,
            status=status,
            delay=delay,
            config_manager=config_manager,
        )
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
        delay: float = 0,
        config_manager=None,
    ):
        super().__init__(
            name=name,
            cid=cid,
            adapter=adapter,
            host=host,
            port=port,
            gpib=gpib,
            status=status,
            delay=delay,
            config_manager=config_manager,
        )
        self.start_frequency: float = None
        self.stop_frequency: float = None


class RohdeSchwarzSpectrumFsek30Manager(DeviceManager):
    name = "Rohde Schwarz Spectrum FSEK 30"
    main_widget_class = "interface.views.SpectrumTabWidget"
    config_class = RohdeSchwarzSpectrumFsek30Config
    configs = DeviceConfigList()
    event_manager = DeviceEventManager()


class ScontelSisBlockConfig(DeviceConfig):
    signal_bias_dev = pyqtSignal(str)
    signal_ctrl_dev = pyqtSignal(str)

    def __init__(
        self,
        name: str,
        cid: int,
        adapter: Optional[str] = None,
        host: Optional[str] = None,
        port: Union[str, int, None] = None,
        gpib: int = 0,
        status: str = settings.NOT_INITIALIZED,
        bias_dev: str = "DEV4",
        ctrl_dev: str = "DEV3",
        delay: float = 0,
        config_manager=None,
    ):
        super().__init__(
            name=name,
            cid=cid,
            adapter=adapter,
            host=host,
            port=port,
            gpib=gpib,
            status=status,
            delay=delay,
            config_manager=config_manager,
        )
        self._bias_dev = bias_dev
        self._ctrl_dev = ctrl_dev
        self.bias_short_status = "1"
        self.ctrl_short_status = "1"
        self.thread_stream = False
        self.thread_ctrl_scan = False
        self.thread_bias_scan = False

    @pyqtProperty("QString", notify=signal_bias_dev)
    def bias_dev(self):
        return self._bias_dev

    @bias_dev.setter
    def bias_dev(self, value: str):
        self._bias_dev = value
        self.signal_bias_dev.emit(value)

    def set_bias_dev(self, bias_dev: str):
        self.bias_dev = bias_dev

    @pyqtProperty("QString", notify=signal_ctrl_dev)
    def ctrl_dev(self):
        return self._ctrl_dev

    @ctrl_dev.setter
    def ctrl_dev(self, value: str):
        self._ctrl_dev = value
        self.signal_ctrl_dev.emit(value)

    def set_ctrl_dev(self, ctrl_dev: str):
        self.ctrl_dev = ctrl_dev

    def dict(self):
        old_dict = super().dict()
        new_dict = {
            "bias_dev": self._bias_dev,
            "ctrl_dev": self._ctrl_dev,
        }
        old_dict.update(new_dict)
        return old_dict


class ScontelSisBlockManager(DeviceManager):
    name = "Scontel SIS Block"
    main_widget_class = "interface.views.BlockTabWidget"
    config_class = ScontelSisBlockConfig
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
    ScontelSisBlockManager.restore_config(qsettings)


def store_configs(qsettings):
    KeithleyPowerSupplyManager.store_config(qsettings)
    PrologixManager.store_config(qsettings)
    AgilentSignalGeneratorManager.store_config(qsettings)
    RigolPowerSupplyManager.store_config(qsettings)
    SumitomoF70Manager.store_config(qsettings)
    LakeShoreTemperatureControllerManager.store_config(qsettings)
    RohdeSchwarzVnaZva67Manager.store_config(qsettings)
    RohdeSchwarzSpectrumFsek30Manager.store_config(qsettings)
    ScontelSisBlockManager.store_config(qsettings)
