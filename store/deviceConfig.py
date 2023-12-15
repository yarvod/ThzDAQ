from typing import Union

from PyQt5.QtCore import QObject, pyqtProperty, pyqtSignal

# Developers
AGILENT = "Agilent"
ARDUINO = "Arduino"
LEADSHINE = "LeadShine"
LAKESHORE = "LakeShore"
SCONTEL = "Scontel"
SRS = "Stanford Research Systems"
NI = "National Instruments"
ROHDESCHWARZ = "Rohde Schwarz"
SUMITOMO = "Sumitomo"
RIGOL = "Rigol"
KEITHLEY = "Keithley"
PROLOGIX = "Prologix"
PFEIFFER = "Pfeiffer"

DEVICES = {KEITHLEY}


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
        status: str = "",
    ):
        super().__init__()
        self._name = name
        self.cid = cid
        self.adapter = adapter
        self.host = host
        self.port = port
        self.gpib = gpib
        self.status = status

    def __str__(self):
        return f"DeviceConfig(cid={self.cid}, adapter={self._adapter}, host={self._host}, port={self._port}, gpib={self._gpib}, status={self._status})"

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


class DeviceManager:
    name = ""
    last_id = 0
    config_class: DeviceConfig = DeviceConfig
    configs: DeviceConfigList[DeviceConfig] = DeviceConfigList()

    @classmethod
    def add_config(cls, *args, **kwargs) -> int:
        cls.last_id += 1
        cls.configs.append(
            cls.config_class(name=cls.name, cid=cls.last_id, *args, **kwargs)
        )
        return cls.last_id

    @classmethod
    def get_config(cls, cid: int) -> Union[DeviceConfig, None]:
        return cls.configs.filter(cid=cid).first()
