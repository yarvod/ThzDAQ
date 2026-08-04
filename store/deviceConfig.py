from typing import Union, Optional, Type, Any

from PySide6.QtCore import QObject, Property, QSettings, QSignalBlocker, Signal

import settings
from utils.dock import Dock
from utils.functions import import_class


class DeviceConfig(QObject):
    signal_name = Signal(str)
    signal_adapter = Signal(str)
    signal_host = Signal(str)
    signal_port = Signal(str)
    signal_gpib = Signal(int)
    signal_status = Signal(str)

    def __init__(
        self,
        name: str,
        cid: int,
        adapter: Optional[str] = None,
        host: Optional[str] = None,
        port: Union[str, int, None] = None,
        gpib: int = 0,
        status: str = settings.NOT_INITIALIZED,
        delay: float = 0,
        config_manager: Type["DeviceManager"] = None,
    ):
        super().__init__()
        self._name = ""
        self.name = name
        self.cid = cid
        self.dock_name = None
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

    @Property("QString", notify=signal_name)
    def name(self):
        return self._name

    @name.setter
    def name(self, value: str):
        value = str(value).strip()
        if not value:
            raise ValueError("Device name cannot be empty")
        self._name = value
        self.signal_name.emit(value)

    @Property("QString", notify=signal_adapter)
    def adapter(self):
        return self._adapter

    @adapter.setter
    def adapter(self, value: str):
        self._adapter = value
        self.signal_adapter.emit(value)

    @Property("QString", notify=signal_host)
    def host(self):
        return self._host

    @host.setter
    def host(self, value: str):
        self._host = value
        self.signal_host.emit(value)

    @Property("QString", notify=signal_port)
    def port(self):
        return self._port

    @port.setter
    def port(self, value: str):
        self._port = value
        self.signal_port.emit(value)

    @Property("int", notify=signal_gpib)
    def gpib(self):
        return self._gpib

    @gpib.setter
    def gpib(self, value: str):
        self._gpib = int(value)
        self.signal_gpib.emit(int(value))

    @Property("QString", notify=signal_status)
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
            name=self._name,
            cid=self.cid,
            adapter=self._adapter,
            host=self._host,
            port=self._port,
            gpib=int(self._gpib),
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
    configs_updated = Signal()


class DeviceManager:
    name = ""
    last_id = 0
    config_class: DeviceConfig = DeviceConfig
    configs: DeviceConfigList[DeviceConfig] = DeviceConfigList()
    setup_widget = None
    main_widget_class = None
    event_manager: QObject = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.event_manager = DeviceEventManager()

    @classmethod
    def default_config_name(cls, cid: Optional[int] = None) -> str:
        if cid is None:
            cid = cls.last_id + 1
        return f"{cls.name} {cid}"

    @classmethod
    def normalize_config_name(cls, name, cid: int) -> str:
        normalized = str(name).strip() if name is not None else ""
        return normalized or cls.default_config_name(cid)

    @classmethod
    def add_config(cls, **kwargs) -> int:
        cls.last_id += 1
        config_name = cls.normalize_config_name(
            kwargs.pop("name", None),
            cls.last_id,
        )
        config = cls.config_class(
            name=config_name,
            cid=cls.last_id,
            config_manager=cls,
            **kwargs,
        )
        config.dock_name = cls.default_config_name(config.cid)
        cls.configs.append(config)
        if cls.event_manager is not None:
            cls.event_manager.configs_updated.emit()
        if cls.main_widget_class:
            Dock.add_widget_to_dock(
                name=config.dock_name,
                title=config.name,
                widget_class=import_class(cls.main_widget_class),
                cid=config.cid,
                menu="device",
            )
        return cls.last_id

    @classmethod
    def rename_config(cls, cid: int, name: str, persist: bool = True) -> str:
        config = cls.get_config(cid)
        if config is None:
            raise ValueError(f"Device configuration {cid} does not exist")

        name = cls.normalize_config_name(name, cid)
        if name == config.name:
            return name

        config.name = name
        if cls.main_widget_class and config.dock_name:
            Dock.rename_widget_in_dock(config.dock_name, name)
        if cls.event_manager is not None:
            cls.event_manager.configs_updated.emit()
        if persist:
            cls.persist_config()
        return name

    @classmethod
    def get_config(cls, cid: int) -> DeviceConfig | Any:
        return cls.configs.filter(cid=cid).first()

    @classmethod
    def update_combobox(cls, combobox):
        selected_cid = combobox.currentData()
        selected_text = combobox.currentText()
        blocker = QSignalBlocker(combobox)
        combobox.clear()
        for config in cls.configs:
            combobox.addItem(config.name, config.cid)

        selected_index = combobox.findData(selected_cid)
        if selected_index < 0 and selected_text:
            selected_index = combobox.findText(selected_text)
        if selected_index >= 0:
            combobox.setCurrentIndex(selected_index)
        del blocker

    @classmethod
    def store_config(cls, qsettings):
        configs = [c.dict() for c in cls.configs]
        qsettings.setValue(f"Configs/{cls.name}", configs)

    @classmethod
    def persist_config(cls, qsettings=None) -> bool:
        if qsettings is None:
            qsettings = QSettings("settings.ini", QSettings.IniFormat)
        cls.store_config(qsettings)
        qsettings.sync()
        return qsettings.status() == QSettings.Status.NoError

    @classmethod
    def restore_config(cls, qsettings):
        configs = qsettings.value(f"Configs/{cls.name}", None)
        if not configs:
            return
        for stored_config in configs:
            cls.add_config(**cls.restore_config_kwargs(stored_config))
        cls.add_configs_to_setup_widget()

    @classmethod
    def restore_config_kwargs(cls, stored_config: dict) -> dict:
        config = dict(stored_config)
        config.pop("cid", None)
        stored_name = config.pop("name", None)
        legacy_name = config.pop("_name", None)
        if stored_name is None and legacy_name and legacy_name != cls.name:
            stored_name = legacy_name
        config["name"] = cls.normalize_config_name(stored_name, cls.last_id + 1)
        return config

    @classmethod
    def add_configs_to_setup_widget(cls):
        assert cls.setup_widget is not None, "You must set SetUpWidget reference"
        for config in cls.configs:
            cls.setup_widget.create_device_info_widget(config, **config.dict())

    @classmethod
    def delete_config(cls, cid: int, persist: bool = True):
        config = cls.configs.filter(cid=cid).first()
        if config is None:
            return
        if cls.main_widget_class and config.dock_name:
            Dock.delete_widget_from_dock(name=config.dock_name)
        index = cls.configs.get_index_by_cid(cid=cid)
        if index is not None:
            cls.configs.delete_by_index(index)
            if persist:
                cls.persist_config()
            if cls.event_manager is not None:
                cls.event_manager.configs_updated.emit()
