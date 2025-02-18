from PySide6.QtCore import QObject, Property, Signal


class GridAngleModel(QObject):
    value = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._val = "0"

    @Property("QString", notify=value)
    def val(self):
        return self._val

    @val.setter
    def val(self, val: str):
        self._val = val
        self.value.emit(val)
