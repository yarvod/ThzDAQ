from PySide6.QtCore import QObject, Property, Signal


class GridAngleModel(QObject):
    value_signal = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0

    @Property(float)
    def value(self):
        return self._value

    @value.setter
    def value(self, val: float):
        self._value = val
        self.value_signal.emit(val)
