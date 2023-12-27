from PyQt5.QtCore import QObject, pyqtProperty, pyqtSignal


class YigFrequencyModel(QObject):
    signal_value = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0

    @pyqtProperty("float", notify=signal_value)
    def value(self):
        return self._value

    @value.setter
    def value(self, value: float):
        self._value = value
        self.signal_value.emit(value)
