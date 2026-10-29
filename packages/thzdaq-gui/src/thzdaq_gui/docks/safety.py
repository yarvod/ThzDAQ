"""Setup → Safety: the bench limits, the safe state and the hardware protection
of the profile (its safety section), edited in tables and saved through the
lab, which checks them before anything is applied.

A value is typed in the unit its quantity is shown in (mV, µA, GHz); the profile
keeps SI. An empty cell is no limit.
"""

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api.devices import DeviceInfo, QuantityInfo

from thzdaq_gui import profile as fmt
from thzdaq_gui import theme
from thzdaq_gui.fields import default_prefix
from thzdaq_gui.forms import saved_or_told

NUMBERS = ("float", "int")
SWITCH = ("Off", "On")  # a switch in the safe state

# Devices and the quantities rows may name, by ref and key
Choices = Dict[str, Tuple[DeviceInfo, Dict[str, QuantityInfo]]]


def settable(session, numbers_only: bool) -> Choices:
    found: Choices = {}
    for info in session.devices():
        quantities = {
            q.key: q
            for q in session.description(info.ref).quantities
            if q.settable and (q.kind in NUMBERS or not numbers_only)
        }
        if quantities:
            found[info.ref] = (info, quantities)
    return found


def as_number(text: str, factor: float, where: str) -> Optional[float]:
    """A number typed in a display unit, to SI; empty: none."""
    text = text.strip()
    if not text:
        return None
    try:
        return float(f"{float(text) * factor:.12g}")
    except ValueError:
        raise ValueError(f"{where}: {text!r} is not a number") from None


class QuantityTable(QTableWidget):
    """Rows that name a device and one of its quantities, then values of it in
    the unit the quantity is shown in."""

    FIXED = ("Device", "Quantity", "Unit")

    def __init__(self, choices: Choices, columns: Sequence[str], parent=None):
        super().__init__(0, len(self.FIXED) + len(columns), parent)
        self.choices = choices
        self.setHorizontalHeaderLabels([*self.FIXED, *columns])
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setMinimumHeight(140)

    def add_row(self, ref: Optional[str] = None, key: Optional[str] = None) -> int:
        row = self.rowCount()
        self.insertRow(row)
        device = QComboBox()
        for found, (info, _) in self.choices.items():
            device.addItem(info.title, found)
            device.setItemData(device.count() - 1, found, Qt.ToolTipRole)
        device.setCurrentIndex(max(0, device.findData(ref)))
        quantity = QComboBox()
        self.setCellWidget(row, 0, device)
        self.setCellWidget(row, 1, quantity)
        unit = QTableWidgetItem()
        unit.setFlags(unit.flags() & ~Qt.ItemIsEditable)
        self.setItem(row, 2, unit)
        device.currentIndexChanged.connect(lambda: self.fill(device, quantity))
        quantity.currentIndexChanged.connect(lambda: self.chosen(quantity))
        self.fill(device, quantity, key)
        return row

    def fill(self, device: QComboBox, quantity: QComboBox, key=None) -> None:
        """The quantities of the device chosen in a row."""
        _, quantities = self.choices.get(device.currentData(), (None, {}))
        quantity.blockSignals(True)
        quantity.clear()
        for found in quantities.values():
            quantity.addItem(found.title, found.key)
        quantity.setCurrentIndex(max(0, quantity.findData(key)))
        quantity.blockSignals(False)
        self.chosen(quantity)

    def chosen(self, quantity: QComboBox) -> None:
        row = self.row_of(quantity)
        self.item(row, 2).setText(self.unit(row)[0])
        self.quantity_shown(row)

    def quantity_shown(self, row: int) -> None:
        """A row's quantity is chosen anew: its value cells follow it."""

    def row_of(self, widget: QWidget) -> int:
        return next(
            row for row in range(self.rowCount()) if widget in self.widgets(row)
        )

    def widgets(self, row: int) -> Tuple[QWidget, ...]:
        return tuple(
            self.cellWidget(row, column) for column in range(self.columnCount())
        )

    def named(self, row: int) -> Tuple[str, Optional[QuantityInfo]]:
        """(device ref, quantity) of a row."""
        ref = self.cellWidget(row, 0).currentData()
        _, quantities = self.choices.get(ref, (None, {}))
        return ref, quantities.get(self.cellWidget(row, 1).currentData())

    def unit(self, row: int) -> Tuple[str, float]:
        """(symbol, factor) of the unit a row's values are typed in."""
        ref, quantity = self.named(row)
        if quantity is None:
            return "", 1.0
        info, _ = self.choices[ref]
        wanted = default_prefix(info.kind, quantity.key, quantity.unit)
        for prefix in quantity.prefixes:
            if prefix.name == wanted:
                return f"{prefix.name}{quantity.unit}", prefix.factor
        return quantity.unit, 1.0

    def where(self, row: int) -> str:
        ref, quantity = self.named(row)
        return f"{ref} {quantity.key if quantity else ''}".strip()

    def text(self, row: int, column: int) -> str:
        item = self.item(row, column)
        return item.text() if item is not None else ""

    def remove_selected(self) -> None:
        for row in sorted(
            {index.row() for index in self.selectedIndexes()}, reverse=True
        ):
            self.removeRow(row)


class LimitsTable(QuantityTable):
    """Bench limits: a row per quantity, an empty cell is no limit."""

    def __init__(self, choices: Choices, parent=None):
        super().__init__(choices, list(fmt.LIMIT_KEYS.values()), parent)

    def add_limit(self, ref: str, key: str, limit: Mapping[str, float]) -> None:
        row = self.add_row(ref, key)
        _, factor = self.unit(row)
        for column, name in enumerate(fmt.LIMIT_KEYS, len(self.FIXED)):
            value = limit.get(name)
            text = "" if value is None else f"{value / factor:.12g}"
            self.setItem(row, column, QTableWidgetItem(text))

    def limits(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        """As the profile holds them (SI); rows without a value are left out."""
        found: Dict[str, Dict[str, Dict[str, float]]] = {}
        for row in range(self.rowCount()):
            ref, quantity = self.named(row)
            _, factor = self.unit(row)
            limit = {}
            for column, name in enumerate(fmt.LIMIT_KEYS, len(self.FIXED)):
                where = f"{self.where(row)} {name}"
                value = as_number(self.text(row, column), factor, where)
                if value is not None:
                    limit[name] = value
            if quantity is not None and limit:
                found.setdefault(ref, {})[quantity.key] = limit
        return found


class SafeStateTable(QuantityTable):
    """The safe state: a value per quantity, set in the order of the rows."""

    VALUE = len(QuantityTable.FIXED)

    def __init__(self, choices: Choices, parent=None):
        super().__init__(choices, ["Value"], parent)

    def quantity_shown(self, row: int) -> None:
        """A switch or a choice takes its value from a list, a number is typed."""
        _, quantity = self.named(row)
        self.removeCellWidget(row, self.VALUE)
        options = ()
        if quantity is not None and quantity.kind == "bool":
            options = SWITCH
        elif quantity is not None and quantity.choices:
            options = quantity.choices
        if options:
            combo = QComboBox()
            combo.addItems(options)
            self.setCellWidget(row, self.VALUE, combo)
        elif self.item(row, self.VALUE) is None:
            self.setItem(row, self.VALUE, QTableWidgetItem())

    def add_value(self, ref: str, key: str, value: Any) -> None:
        row = self.add_row(ref, key)
        combo = self.cellWidget(row, self.VALUE)
        if isinstance(combo, QComboBox):
            shown = SWITCH[bool(value)] if isinstance(value, bool) else str(value)
            combo.setCurrentIndex(max(0, combo.findText(shown)))
        else:
            _, factor = self.unit(row)
            text = (
                f"{value / factor:.12g}" if isinstance(value, (int, float)) else value
            )
            self.item(row, self.VALUE).setText(str(text))

    def values(self) -> Dict[str, Dict[str, Any]]:
        found: Dict[str, Dict[str, Any]] = {}
        for row in range(self.rowCount()):
            ref, quantity = self.named(row)
            if quantity is None:
                continue
            combo = self.cellWidget(row, self.VALUE)
            if isinstance(combo, QComboBox):
                text = combo.currentText()
                value: Any = text == SWITCH[1] if quantity.kind == "bool" else text
            elif quantity.kind in NUMBERS:
                _, factor = self.unit(row)
                value = as_number(self.text(row, self.VALUE), factor, self.where(row))
            else:
                value = self.text(row, self.VALUE).strip() or None
            if value is not None:
                found.setdefault(ref, {})[quantity.key] = value
        return found


def table_box(title: str, table: QuantityTable, add_text: str, note: str) -> QGroupBox:
    """A table under what it means, with buttons to add a row and remove the
    selected ones."""
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    text = QLabel(note)
    text.setWordWrap(True)
    text.setProperty("role", "muted")
    layout.addWidget(text)
    layout.addWidget(table)
    buttons = QHBoxLayout()
    add = QPushButton(theme.icon("plus"), add_text)
    add.clicked.connect(lambda: table.add_row())
    remove = QPushButton(theme.icon("delete-outline"), "Remove selected")
    remove.clicked.connect(table.remove_selected)
    buttons.addWidget(add)
    buttons.addWidget(remove)
    buttons.addStretch()
    layout.addLayout(buttons)
    return box


class SafetyDialog(QDialog):
    """The safety section of the profile. Save hands it to the lab; the dialog
    stays open while the lab refuses it (min above max, a rate without step)."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Safety")
        self.setWindowIcon(theme.icon("shield-check-outline"))
        self.resize(900, 640)
        safety = session.profile().profile.get(fmt.SAFETY) or {}
        self.limits = LimitsTable(settable(session, numbers_only=True))
        for ref, by_key in (safety.get(fmt.LIMITS) or {}).items():
            for key, limit in by_key.items():
                self.limits.add_limit(ref, key, limit)
        self.safe_state = SafeStateTable(settable(session, numbers_only=False))
        for ref, values in (safety.get(fmt.SAFE_STATE) or {}).items():
            for key, value in values.items():
                self.safe_state.add_value(ref, key, value)
        self.protection = QCheckBox(
            "Hardware protection: supplies get OVP and OCP from the limits"
        )
        self.protection.setChecked(bool(safety.get(fmt.HARDWARE_PROTECTION)))
        layout = QVBoxLayout(self)
        layout.addWidget(
            table_box(
                "Limits", self.limits, "Add limit",
                "A value beyond min..max is refused; beyond the warn range people "
                "are asked first; a larger change than step goes in steps at rate.",
            )
        )  # fmt: skip
        layout.addWidget(
            table_box(
                "Safe state", self.safe_state, "Add value",
                "Set in this order by Safe state and when the daemon stops "
                "measurements.",
            )
        )  # fmt: skip
        layout.addWidget(self.protection)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_values)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def safety(self) -> Dict[str, Any]:
        """The section as the profile holds it; ValueError for text that is
        not a number."""
        return {
            fmt.LIMITS: self.limits.limits(),
            fmt.SAFE_STATE: self.safe_state.values(),
            fmt.HARDWARE_PROTECTION: self.protection.isChecked(),
        }

    def save(self) -> None:
        profile = fmt.changed(self.session.profile().profile)
        profile[fmt.SAFETY] = self.safety()
        self.session.update_profile(profile)

    def accept_values(self) -> None:
        saved_or_told(self, "Safety", self.save)
