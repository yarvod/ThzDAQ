from PyQt5.QtCore import QObject, pyqtProperty, pyqtSignal


class GridAngleModel(QObject):
    value = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._val = "0"

    @pyqtProperty("QString", notify=value)
    def val(self):
        return self._val

    @val.setter
    def val(self, val: str):
        self._val = val
        self.value.emit(val)
