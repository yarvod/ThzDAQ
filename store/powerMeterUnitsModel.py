from PySide6.QtCore import QObject, Property, Signal

from store.state import state


class PowerMeterUnitModel(QObject):
    value = Signal(str)
    value_pretty = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._val = "DBM"
        self.values = state.NRX_UNITS
        self.values_reverse = state.NRX_UNITS_REVERSE

    @Property("QString", notify=value)
    def val(self):
        return self._val

    @val.setter
    def val(self, val: str):
        self._val = val
        self.value.emit(val)
        self.value_pretty.emit(self.val_pretty)

    def set_value(self, val: str):
        self.val = val

    @property
    def val_pretty(self):
        return self.values.get(self._val, "dBm")


power_meter_unit_model = PowerMeterUnitModel()
