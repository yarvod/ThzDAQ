"""Forms built from parameters (procedures, device settings) and device slots.

Editors show display units (GHz, mV); values() returns SI values ready for
Procedure(**values).
"""

from typing import Any, Callable, Dict, List, Mapping, Optional, Type

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QWidget,
)
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.parameters import Parameter, Sweep
from thzdaq_core.measurements.procedure import Procedure

LIMIT = 1e15


class _Compact:
    """Width from a typical value, not from the range.

    Qt sizes a spin box for its longest possible text: with ±1e15 and six
    decimals that is ~180 px per box, and a sweep row of three made forms and
    docks 800 px wide.
    """

    DIGITS = 4  # before the point in a typical value
    SHORTEST = "0.00"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Spin boxes default to Minimum: never narrower than the size hint
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # The minimum follows the shown value
        self.valueChanged.connect(lambda _: self.updateGeometry())

    def sample(self) -> str:
        decimals = self.decimals() if hasattr(self, "decimals") else 0
        return "-" + "0" * self.DIGITS + ("." + "0" * decimals if decimals else "")

    def _width(self, text: str) -> int:
        metrics = self.fontMetrics()
        extra = self.prefix() + self.suffix()
        # frame, padding and the up/down buttons
        return metrics.horizontalAdvance(text + extra) + 44

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        text = max(self.sample(), self.cleanText(), key=len)
        return QSize(min(hint.width(), self._width(text)), hint.height())

    def minimumSizeHint(self) -> QSize:
        # Never narrower than the value it shows: a squeezed row must not clip it
        hint = super().minimumSizeHint()
        text = max(self.SHORTEST, self.cleanText(), key=len)
        return QSize(min(hint.width(), self._width(text)), hint.height())

    # Arrows and the wheel change the digit at the cursor (as in the old app):
    # 123|.45 steps by 1, 12|3.45 by 10, 123.|45 and 123.4|5 by 0.1, 123.45| by 0.01
    def _layout(self):
        """(first digit, decimal point, end) positions of the number in the text."""
        text = self.lineEdit().text()
        start = len(self.prefix())
        end = len(text) - len(self.suffix())
        if text[start : start + 1] in ("+", "-"):
            start += 1
        point = -1
        if isinstance(self, QDoubleSpinBox) and self.decimals() > 0:
            point = text.find(self.locale().decimalPoint(), start, end)
        return start, (end if point < 0 else point), end

    def stepBy(self, steps: int) -> None:
        edit = self.lineEdit()
        start, point, end = self._layout()
        cursor = min(max(edit.cursorPosition(), start), end)
        if cursor <= start:
            exponent = max(point - start - 1, 0)  # before the number: its first digit
        elif cursor <= point:
            exponent = point - cursor
        else:
            exponent = -max(1, cursor - point - 1)
        decimals = self.decimals() if isinstance(self, QDoubleSpinBox) else 0
        exponent = max(exponent, -decimals)
        step = 10.0**exponent if decimals else 10 ** max(exponent, 0)
        from_point = point - max(cursor, start)
        usual = self.singleStep()
        self.setSingleStep(step)
        try:
            super().stepBy(steps)
        finally:
            self.setSingleStep(usual)
        # The cursor stays on the same digit when the number gets longer or shorter
        start, point, end = self._layout()
        edit.deselect()
        edit.setCursorPosition(min(max(point - from_point, start), end))


class CompactDoubleSpinBox(_Compact, QDoubleSpinBox):
    pass


class CompactSpinBox(_Compact, QSpinBox):
    DIGITS = 6
    SHORTEST = "000"


def compact_combo(combo: QComboBox, characters: int = 14) -> QComboBox:
    """A combo box as wide as a short name; the list itself shows the long ones."""
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(characters)
    return combo


def to_si(value: float, scale: float) -> float:
    """Display value -> SI, without 2.6 mV turning into 0.0026000000000000003 V."""
    return float(f"{value * scale:.12g}")


def _double_spin(parameter: Parameter) -> QDoubleSpinBox:
    spin = CompactDoubleSpinBox()
    spin.setDecimals(4)
    scale = parameter.display_scale
    minimum = getattr(parameter, "minimum", None)
    maximum = getattr(parameter, "maximum", None)
    spin.setRange(
        -LIMIT if minimum is None else minimum / scale,
        LIMIT if maximum is None else maximum / scale,
    )
    if parameter.display_unit:
        spin.setSuffix(f" {parameter.display_unit}")
    spin.setKeyboardTracking(False)
    return spin


class Editor:
    """Widget + getter/setter for one parameter, values in SI."""

    def __init__(
        self, widget: QWidget, get: Callable[[], Any], set_: Callable[[Any], None]
    ):
        self.widget = widget
        self.get = get
        self.set = set_


def make_editor(parameter: Parameter) -> Editor:
    kind = parameter.kind
    scale = parameter.display_scale
    if kind == "float":
        spin = _double_spin(parameter)
        return Editor(
            spin, lambda: to_si(spin.value(), scale), lambda v: spin.setValue(v / scale)
        )
    if kind == "int":
        spin = CompactSpinBox()
        minimum = getattr(parameter, "minimum", None)
        maximum = getattr(parameter, "maximum", None)
        spin.setRange(
            -(2**31) if minimum is None else int(minimum),
            2**31 - 1 if maximum is None else int(maximum),
        )
        return Editor(spin, spin.value, lambda v: spin.setValue(int(v)))
    if kind == "bool":
        check = QCheckBox()
        return Editor(check, check.isChecked, check.setChecked)
    if kind == "choice":
        combo = QComboBox()
        for choice in parameter.choices:
            combo.addItem(str(choice), choice)
        return Editor(
            combo, combo.currentData, lambda v: combo.setCurrentIndex(combo.findData(v))
        )
    if kind == "multi_choice":
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        checks = []
        for choice in parameter.choices:
            check = QCheckBox(str(choice))
            row.addWidget(check)
            checks.append((choice, check))
        row.addStretch()

        def get_multi():
            return tuple(choice for choice, check in checks if check.isChecked())

        def set_multi(values):
            for choice, check in checks:
                check.setChecked(choice in values)

        return Editor(box, get_multi, set_multi)
    if kind == "string_list":
        line = QLineEdit()
        line.setPlaceholderText("comma separated")
        return Editor(
            line,
            lambda: parameter.parse(line.text()),
            lambda v: line.setText(", ".join(v)),
        )
    if kind == "float_list":
        line = QLineEdit()
        line.setPlaceholderText(f"comma separated, {parameter.display_unit}")
        return Editor(
            line,
            lambda: parameter.parse(line.text()),
            lambda v: line.setText(", ".join(f"{x / scale:g}" for x in v)),
        )
    if kind == "sweep":
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        start, stop = _double_spin(parameter), _double_spin(parameter)
        points = CompactSpinBox()
        points.setRange(1, getattr(parameter, "max_points", 100001))
        points.setSuffix(" pts")
        for widget in (start, stop, points):
            row.addWidget(widget)

        def get_sweep():
            return Sweep(
                to_si(start.value(), scale), to_si(stop.value(), scale), points.value()
            )

        def set_sweep(value: Sweep):
            start.setValue(value.start / scale)
            stop.setValue(value.stop / scale)
            points.setValue(value.points)

        return Editor(box, get_sweep, set_sweep)
    line = QLineEdit()
    return Editor(
        line, lambda: parameter.parse(line.text()), lambda v: line.setText(str(v))
    )


class ParameterForm(QWidget):
    """Editors for a set of parameters (a procedure's or a device kind's settings)."""

    changed = Signal()  # an editor was changed by the user

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QFormLayout(self)
        # Fields as wide as they need, not as the dock: no stretched number boxes
        self.layout_.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.procedure_class: Optional[Type[Procedure]] = None
        self.parameters: Dict[str, Parameter] = {}
        self.editors: Dict[str, Editor] = {}

    def set_procedure(self, procedure_class: Type[Procedure]) -> None:
        self.procedure_class = procedure_class
        self.set_parameters(procedure_class.parameters())

    def set_parameters(self, parameters: Mapping[str, Parameter]) -> None:
        while self.layout_.rowCount():
            self.layout_.removeRow(0)
        self.editors.clear()
        self.parameters = dict(parameters)
        for name, parameter in self.parameters.items():
            editor = make_editor(parameter)
            if (
                parameter.default is not None
                and parameter.describe()["required"] is False
            ):
                editor.set(parameter.default)
            if parameter.help:
                editor.widget.setToolTip(parameter.help)
            label = QLabel(parameter.label)
            label.setToolTip(name)
            self.layout_.addRow(label, editor.widget)
            self.editors[name] = editor
            self._watch(editor.widget)

    def _watch(self, widget: QWidget) -> None:
        for child in [widget, *widget.findChildren(QWidget)]:
            if isinstance(child, QCheckBox):
                child.toggled.connect(self.changed)
            elif isinstance(child, QComboBox):
                child.currentIndexChanged.connect(self.changed)
            elif isinstance(child, (QSpinBox, QDoubleSpinBox, QLineEdit)):
                child.editingFinished.connect(self.changed)

    def values(self) -> Dict[str, Any]:
        """SI values; raises ProcedureError listing every invalid field."""
        values, problems = {}, []
        for name, editor in self.editors.items():
            parameter = self.parameters[name]
            try:
                values[name] = parameter.validate(editor.get())
            except ProcedureError as e:
                problems.append(f"{parameter.label}: {e}")
        if problems:
            raise ProcedureError("; ".join(problems))
        return values

    def set_values(self, values: Mapping[str, Any]) -> None:
        for name, value in values.items():
            if name in self.editors:
                try:
                    self.editors[name].set(value)
                except (TypeError, ValueError, AttributeError):
                    pass

    def procedure(self) -> Procedure:
        procedure = self.procedure_class(**self.values())
        procedure.validate()
        return procedure


def capability_text(capabilities) -> str:
    caps = capabilities if isinstance(capabilities, tuple) else (capabilities,)
    return " + ".join(c.__name__ for c in caps if c is not object) or "any device"


class DeviceSlotsForm(QWidget):
    """Which station device plays each procedure slot; only suitable devices are listed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QFormLayout(self)
        self.combos: Dict[str, QComboBox] = {}

    def set_slots(
        self,
        slots: Mapping[str, Any],
        station,
        titles: Callable[[str], str] = lambda slot: slot,
        preferred: Optional[Mapping[str, str]] = None,
        kinds: Optional[Mapping[str, str]] = None,
    ) -> None:
        current = {**(preferred or {}), **self.mapping()}
        while self.layout_.rowCount():
            self.layout_.removeRow(0)
        self.combos.clear()
        # Devices chosen before are kept; free slots take the next unused device
        taken = {current[slot] for slot in slots if current.get(slot)}
        for slot, capabilities in slots.items():
            combo = compact_combo(QComboBox(), 14)
            caps = capabilities if isinstance(capabilities, tuple) else (capabilities,)
            caps = tuple(c for c in caps if c is not object)
            devices = station.find(caps) if station is not None else []
            kind = (kinds or {}).get(slot)
            if kind and any(info.kind == kind for info in devices):
                # A SIS bias slot lists SIS biases, not every supply channel
                devices = [info for info in devices if info.kind == kind]
            for info in devices:
                combo.addItem(info.title, info.ref)
                combo.setItemData(combo.count() - 1, info.ref, Qt.ToolTipRole)
            wanted = current.get(slot, slot)
            index = combo.findData(wanted)
            if index < 0:
                # First suitable device not used by another slot yet
                index = next(
                    (i for i in range(combo.count()) if combo.itemData(i) not in taken),
                    0 if combo.count() else -1,
                )
            combo.setCurrentIndex(index)
            if combo.currentData():
                taken.add(combo.currentData())
            combo.setToolTip(capability_text(capabilities))
            self.layout_.addRow(titles(slot), combo)
            self.combos[slot] = combo

    def mapping(self) -> Dict[str, str]:
        return {
            slot: combo.currentData()
            for slot, combo in self.combos.items()
            if combo.currentData()
        }

    def unmapped(self) -> List[str]:
        return [slot for slot, combo in self.combos.items() if not combo.currentData()]
