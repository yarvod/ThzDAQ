from typing import Union

from PyQt5.QtCore import QObject, pyqtProperty, pyqtSignal, QSettings

import settings


class AdapterConfig(QObject):
    signal_host = pyqtSignal(str)
    signal_port = pyqtSignal(str)
    signal_status = pyqtSignal(str)

    def __init__(
        self,
        name: str,
        cid: int,
        host: str = None,
        port: Union[str, int] = None,
        status: str = settings.NOT_INITIALIZED,
        config_manager=None,
    ):
        super().__init__()
        self._name = name
        self.cid = cid
        self.host = host
        self.port = port
        self.status = status
        self.config_manager = config_manager

    def __str__(self):
        return f"AdapterConfig(cid={self.cid}, host={self._host}, port={self._port}, status={self._status})"

    __repr__ = __str__

    @property
    def name(self):
        return f"{self._name} {self.cid}"

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
            host=self._host,
            port=self._port,
        )


class AdapterConfigList(list):
    def first(self) -> Union["AdapterConfig", None]:
        try:
            return self[0]
        except IndexError:
            return None

    def last(self) -> Union["AdapterConfig", None]:
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

    def filter(self, **kwargs) -> "AdapterConfigList":
        return self.__class__(self._filter(**kwargs))

    def delete_by_index(self, index: int) -> None:
        del self[index]

    def get_index_by_cid(self, cid: int) -> int:
        return next((i for i, item in enumerate(self) if item.cid == cid), None)


class AdapterManager:
    name = ""
    last_id = 0
    config_class: AdapterConfig = AdapterConfig
    configs: AdapterConfigList[AdapterConfig] = AdapterConfigList()
    setup_widget = None

    @classmethod
    def add_config(cls, **kwargs) -> int:
        cls.last_id += 1
        config = cls.config_class(
            name=cls.name, cid=cls.last_id, config_manager=cls, **kwargs
        )
        cls.configs.append(config)
        return cls.last_id

    @classmethod
    def get_config(cls, cid: int) -> Union[AdapterConfig, None]:
        return cls.configs.filter(cid=cid).first()

    @classmethod
    def store_config(cls):
        configs = [c.dict() for c in cls.configs]
        qsettings = QSettings("ASC", "SIS manager")
        qsettings.setValue(f"Configs/{cls.name}", configs)
        qsettings.sync()

    @classmethod
    def restore_config(cls):
        qsettings = QSettings("ASC", "SIS manager")
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
            cls.setup_widget.create_adapter_info_widget(config, **config.dict())

    @classmethod
    def delete_config(cls, cid: int):
        index = cls.configs.get_index_by_cid(cid=cid)
        if index:
            cls.configs.delete_by_index(index)
