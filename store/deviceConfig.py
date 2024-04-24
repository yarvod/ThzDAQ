from typing import Union

from PyQt5.QtCore import QObject, pyqtProperty, pyqtSignal

import settings
from utils.dock import Dock
from utils.functions import import_class


class DeviceConfig(QObject):
    signal_adapter = pyqtSignal(str)
    signal_host = pyqtSignal(str)
    signal_port = pyqtSignal(str)
    signal_gpib = pyqtSignal(int)
    signal_status = pyqtSignal(str)

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
        super().__init__()
        self._name = name
        self.cid = cid
        self.adapter = adapter
        self.host = host
        self.port = port
        self.gpib = gpib
        self.status = status
        self.delay = delay
        self.config_manager = config_manager

        self.thread_stream = False

    def __str__(self):
        return f"{self.__class__.__name__}(cid={self.cid}, adapter={self._adapter}, host={self._host}, port={self._port}, gpib={self._gpib}, status={self._status})"

    __repr__ = __str__

    @property
    def name(self):
        return f"{self._name} {self.cid}"

    @pyqtProperty("QString", notify=signal_adapter)
    def adapter(self):
        return self._adapter

    @adapter.setter
    def adapter(self, value: str):
        self._adapter = value
        self.signal_adapter.emit(value)

    @pyqtProperty("QString", notify=signal_host)
    def host(self):
        return self._host

    @host.setter
    def host(self, value: str):
        self._host = value
        self.signal_host.emit(value)

    @pyqtProperty("QString", notify=signal_port)
    def port(self):
        return self._port

    @port.setter
    def port(self, value: str):
        self._port = value
        self.signal_port.emit(value)

    @pyqtProperty("int", notify=signal_gpib)
    def gpib(self):
        return self._gpib

    @gpib.setter
    def gpib(self, value: str):
        self._gpib = value
        self.signal_gpib.emit(value)

    @pyqtProperty("QString", notify=signal_status)
    def status(self):
        return self._status

    @status.setter
    def status(self, value: str):
        self._status = value
        self.signal_status.emit(value)

    def set_status(self, status: str):
        self.status = status

    def dict(self):
        return dict(
            _name=self._name,
            cid=self.cid,
            adapter=self._adapter,
            host=self._host,
            port=self._port,
            gpib=self._gpib,
        )


class DeviceConfigList(list):
    def first(self) -> Union["DeviceConfig", None]:
        try:
            return self[0]
        except IndexError:
            return None

    def last(self) -> Union["DeviceConfig", None]:
        try:
            return self[-1]
        except IndexError:
            return None

    def _filter(self, **kwargs) -> filter:
        def _filter(item):
            for key, value in kwargs.items():
                if not getattr(item, key, None) == value:
                    return False
            return True

        return filter(_filter, self)

    def filter(self, **kwargs) -> "DeviceConfigList":
        return self.__class__(self._filter(**kwargs))

    def delete_by_index(self, index: int) -> None:
        del self[index]

    def get_index_by_cid(self, cid: int) -> int:
        return next((i for i, item in enumerate(self) if item.cid == cid), None)

    def list_of_names(self):
        return [config.name for config in self]


class DeviceEventManager(QObject):
    configs_updated = pyqtSignal()


class DeviceManager:
    name = ""
    last_id = 0
    config_class: DeviceConfig = DeviceConfig
    configs: DeviceConfigList[DeviceConfig] = DeviceConfigList()
    setup_widget = None
    main_widget_class = None
    event_manager: QObject = None

    @classmethod
    def add_config(cls, **kwargs) -> int:
        cls.last_id += 1
        config = cls.config_class(
            name=cls.name, cid=cls.last_id, config_manager=cls, **kwargs
        )
        cls.configs.append(config)
        if cls.event_manager is not None:
            cls.event_manager.configs_updated.emit()
        if cls.main_widget_class:
            Dock.add_widget_to_dock(
                name=config.name,
                widget_class=import_class(cls.main_widget_class),
                cid=config.cid,
                menu="device",
            )
        return cls.last_id

    @classmethod
    def get_config(cls, cid: int) -> Union[DeviceConfig, None]:
        return cls.configs.filter(cid=cid).first()

    @classmethod
    def store_config(cls, qsettings):
        configs = [c.dict() for c in cls.configs]
        qsettings.setValue(f"Configs/{cls.name}", configs)

    @classmethod
    def restore_config(cls, qsettings):
        configs = qsettings.value(f"Configs/{cls.name}", None)
        if not configs:
            return
        for config in configs:
            config.pop("cid", None)
            config.pop("_name", None)
            cls.add_config(**config)
        cls.add_configs_to_setup_widget()

    @classmethod
    def add_configs_to_setup_widget(cls):
        assert cls.setup_widget is not None, "You must set SetUpWidget reference"
        for config in cls.configs:
            cls.setup_widget.create_device_info_widget(config, **config.dict())

    @classmethod
    def delete_config(cls, cid: int):
        Dock.delete_widget_from_dock(
            name=cls.configs.filter(cid=cid).first().name,
        )
        index = cls.configs.get_index_by_cid(cid=cid)
        if index is not None:
            cls.configs.delete_by_index(index)
            if cls.event_manager is not None:
                cls.event_manager.configs_updated.emit()
