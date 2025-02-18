from PySide6.QtCore import QObject, Property, Signal


class YigFrequencyModel(QObject):
    signal_value = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0

    @Property("float", notify=signal_value)
    def value(self):
        return self._value

    @value.setter
    def value(self, value: float):
        self._value = value
        self.signal_value.emit(value)
