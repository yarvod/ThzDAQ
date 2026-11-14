"""Value fields with an SI prefix selector, used by the device docks.

A number is typed in the chosen unit (223 with "GHz — ×10⁹"), shown back in
it, and the field reports SI values. The prefixes are those the lab describes
for the value. Edits are applied only on purpose (Set, Enter); until then the
field is marked pending (orange frame).
"""

from typing import Optional, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QWidget,
)
from thzdaq_api.devices import Prefix, QuantityInfo

from thzdaq_gui.forms import CompactDoubleSpinBox
from thzdaq_gui.settings import settings, unit_key

LIMIT = 1e15


def default_prefix(kind: str, key: str, unit: str) -> str:
    """Prefix a field starts with: GHz for generators, mV / µA for a SIS bias, ..."""
    if unit == "Hz":
        return "G"
    if unit == "s":
        return "m"  # aperture and filter times
    if key.startswith("offset_"):
        return "µ"  # SIS offsets: tens of µV, a few µA
    if kind == "sis_bias":
        return "m" if unit == "V" else "µ" if unit == "A" else ""
    if kind == "sis_coil" and unit == "A":
        return "m"
    return ""


class PrefixBox(QComboBox):
    """Prefixes of one unit ("GHz — ×10⁹"); empty (hidden) for dBm, dB, deg.

    Closed, it shows only the unit (GHz), so a row stays narrow; the list
    shows the multipliers.
    """

    def __init__(
        self, prefixes: Sequence[Prefix], unit: str, prefix: str = "", parent=None
    ):
        super().__init__(parent)
        self.unit = unit
        self.factors = {p.name: p.factor for p in prefixes}
        for p in prefixes:
            self.addItem(f"{p.name}{unit} — {p.note}", p.name)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(len(unit) + 2)
        self.view().setMinimumWidth(self.view().sizeHintForColumn(0) + 24)
        index = self.findData(prefix)
        self.setCurrentIndex(index if index >= 0 else max(0, self.findData("")))
        if not self.count():
            self.hide()  # never setVisible(True) here: without a parent it is a window

    def prefix(self) -> str:
        return self.currentData() or ""

    def factor(self) -> float:
        return self.factors[self.prefix()] if self.count() else 1.0

    def symbol(self) -> str:
        return f"{self.prefix()}{self.unit}"

    def paintEvent(self, event) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = self.symbol()
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)


def format_number(value: float, factor: float, symbol: str) -> str:
    return f"{value / factor:.6g} {symbol}".strip()


class QuantityField(QWidget):
    """Editor of one settable quantity: number + prefix, or a choice list."""

    apply_requested = Signal()  # Enter pressed in the number

    def __init__(self, quantity: QuantityInfo, ref: str, kind: str, parent=None):
        super().__init__(parent)
        self.quantity = quantity
        self.unit_key = unit_key(ref, quantity.key)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.choice: Optional[QComboBox] = None
        self.spin: Optional[QDoubleSpinBox] = None
        self.prefix = PrefixBox(
            quantity.prefixes,
            quantity.unit,
            settings().value(self.unit_key)
            or default_prefix(kind, quantity.key, quantity.unit),
        )
        if quantity.kind == "text":
            self.choice = QComboBox()
            for value in quantity.choices:
                self.choice.addItem(str(value), value)
            self.choice.setEditable(not quantity.choices)
            self.choice.currentIndexChanged.connect(lambda _: self.set_pending(True))
            layout.addWidget(self.choice, 1)
        else:
            self.spin = CompactDoubleSpinBox()
            self.spin.DIGITS = 3
            self.spin.setDecimals(6)
            self.spin.setRange(-LIMIT, LIMIT)
            self.spin.setKeyboardTracking(False)
            self.spin.valueChanged.connect(lambda _: self.set_pending(True))
            self.spin.lineEdit().returnPressed.connect(self.apply_requested)
            layout.addWidget(self.spin, 1)
            if not self.prefix.count() and quantity.unit:
                layout.addWidget(QLabel(quantity.unit))
        layout.addWidget(self.prefix)
        self._factor = self.prefix.factor()
        self.prefix.currentIndexChanged.connect(self.prefix_changed)
        self.pending = False

    def value(self):
        if self.choice is not None:
            return self.choice.currentData() or self.choice.currentText()
        return float(f"{self.spin.value() * self._factor:.12g}")

    def set_value(self, value, pending: bool = False) -> None:
        if value is None:
            return
        if self.choice is not None:
            index = self.choice.findData(value)
            if index < 0:
                index = self.choice.findText(str(value))
            if index >= 0:
                self.choice.blockSignals(True)
                self.choice.setCurrentIndex(index)
                self.choice.blockSignals(False)
        else:
            self.spin.blockSignals(True)
            self.spin.setValue(float(value) / self._factor)
            self.spin.blockSignals(False)
        self.set_pending(pending)

    def set_pending(self, pending: bool) -> None:
        self.pending = pending
        target = self.spin if self.spin is not None else self.choice
        target.setProperty("pending", pending)
        target.style().unpolish(target)
        target.style().polish(target)

    def prefix_changed(self) -> None:
        if self.spin is not None:
            si = self.spin.value() * self._factor
            self._factor = self.prefix.factor()
            self.spin.blockSignals(True)
            self.spin.setValue(si / self._factor)
            self.spin.blockSignals(False)
        else:
            self._factor = self.prefix.factor()
        settings().setValue(self.unit_key, self.prefix.prefix())
