"""Forms built from descriptions of the contract: parameters (ParameterInfo of a
procedure or of a device kind's settings) and device slots (SlotInfo).

Editors show display units (GHz, mV); values() returns SI values as JSON
carries them (a sweep is {start, stop, points}). The daemon checks them: a form
only turns what is typed into numbers. Parameters are shown under a line with
the title of their group, and only while their conditions hold (shown_if: the
hot and cold load while hot/cold is on).
"""

from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QWidget,
)
from thzdaq_api.devices import DeviceInfo
from thzdaq_api.errors import LabError
from thzdaq_api.measurements import ParameterInfo, SlotInfo, split_list

from thzdaq_gui import theme

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
        # As Qt sizes a spin box for its longest text (QAbstractSpinBox::sizeHint):
        # the text, a space and the cursor, then the style adds frame and buttons
        advance = self.fontMetrics().horizontalAdvance(
            self.prefix() + text + self.suffix() + " "
        )
        contents = QSize(advance + 2, self.lineEdit().sizeHint().height())
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        return (
            self.style()
            .sizeFromContents(QStyle.CT_SpinBox, option, contents, self)
            .width()
        )

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


def _numbers(text: str, scale: float) -> List[float]:
    """Numbers typed in display units -> SI."""
    try:
        return [to_si(float(item), scale) for item in split_list(text)]
    except ValueError:
        raise ValueError(f"expected numbers, got {text!r}") from None


def _double_spin(parameter: ParameterInfo) -> QDoubleSpinBox:
    spin = CompactDoubleSpinBox()
    spin.setDecimals(4)
    scale = parameter.display_scale
    minimum, maximum = parameter.minimum, parameter.maximum
    spin.setRange(
        -LIMIT if minimum is None else minimum / scale,
        LIMIT if maximum is None else maximum / scale,
    )
    if parameter.display_unit:
        spin.setSuffix(f" {parameter.display_unit}")
    spin.setKeyboardTracking(False)
    return spin


class Editor:
    """Widget + getter/setter for one parameter, values in SI as JSON has them."""

    def __init__(
        self, widget: QWidget, get: Callable[[], Any], set_: Callable[[Any], None]
    ):
        self.widget = widget
        self.get = get
        self.set = set_


def make_editor(parameter: ParameterInfo) -> Editor:
    kind = parameter.kind
    scale = parameter.display_scale
    if kind == "float":
        spin = _double_spin(parameter)
        return Editor(
            spin, lambda: to_si(spin.value(), scale), lambda v: spin.setValue(v / scale)
        )
    if kind == "int":
        spin = CompactSpinBox()
        minimum, maximum = parameter.minimum, parameter.maximum
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
            return [choice for choice, check in checks if check.isChecked()]

        def set_multi(values):
            for choice, check in checks:
                check.setChecked(choice in values)

        return Editor(box, get_multi, set_multi)
    if kind == "text":
        line = QLineEdit()
        return Editor(line, line.text, lambda v: line.setText(f"{v}"))
    if kind == "string_list":
        line = QLineEdit()
        line.setPlaceholderText("comma separated")
        return Editor(
            line,
            lambda: split_list(line.text()),
            lambda v: line.setText(", ".join(v)),
        )
    if kind == "float_list":
        line = QLineEdit()
        line.setPlaceholderText(f"comma separated, {parameter.display_unit}")
        return Editor(
            line,
            lambda: _numbers(line.text(), scale),
            lambda v: line.setText(", ".join(f"{x / scale:g}" for x in v)),
        )
    if kind == "sweep":
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        start, stop = _double_spin(parameter), _double_spin(parameter)
        points = CompactSpinBox()
        points.setRange(1, parameter.max_points or 2**31 - 1)
        points.setSuffix(" pts")
        for widget in (start, stop, points):
            row.addWidget(widget)

        def get_sweep():
            return {
                "start": to_si(start.value(), scale),
                "stop": to_si(stop.value(), scale),
                "points": points.value(),
            }

        def set_sweep(value: Mapping[str, Any]):
            start.setValue(value["start"] / scale)
            stop.setValue(value["stop"] / scale)
            points.setValue(value["points"])

        return Editor(box, get_sweep, set_sweep)
    line = QLineEdit()
    return Editor(line, line.text, lambda v: line.setText(str(v)))


def grouped(
    parameters: Iterable[ParameterInfo],
) -> List[Tuple[str, List[ParameterInfo]]]:
    """Parameters by their group: those without one first, then the groups in
    the order they first come, each in the order given but for those that
    decide whether others are shown (hot/cold on), which lead their group."""
    parameters = list(parameters)
    deciding = {c.parameter for p in parameters for c in p.shown_if}
    groups: Dict[str, List[ParameterInfo]] = {}
    for parameter in sorted(parameters, key=lambda p: p.name not in deciding):
        groups.setdefault(parameter.group, []).append(parameter)
    order = list(dict.fromkeys(p.group for p in parameters))
    return sorted(
        groups.items(), key=lambda item: (item[0] != "", order.index(item[0]))
    )


def group_header(title: str) -> QWidget:
    """The title of a group of parameters on a line across the form."""
    header = QWidget()
    row = QHBoxLayout(header)
    row.setContentsMargins(0, 6, 0, 0)
    label = QLabel(title)
    label.setStyleSheet(f"color: {theme.MUTED}; font-weight: bold;")
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"color: {theme.BORDER};")
    row.addWidget(label)
    row.addWidget(line, 1)
    return header


class ParameterForm(QWidget):
    """Editors for a set of parameters (a procedure's or a device kind's settings)."""

    changed = Signal()  # an editor was changed by the user

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QFormLayout(self)
        # Fields as wide as they need, not as the dock: no stretched number boxes
        self.layout_.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.parameters: Dict[str, ParameterInfo] = {}
        self.editors: Dict[str, Editor] = {}
        self.headers: Dict[
            str, Tuple[QWidget, List[str]]
        ] = {}  # group: its line, names
        self.changed.connect(self.show_used)

    def set_parameters(self, parameters: Iterable[ParameterInfo]) -> None:
        while self.layout_.rowCount():
            self.layout_.removeRow(0)
        self.editors.clear()
        self.headers.clear()
        self.parameters = {parameter.name: parameter for parameter in parameters}
        for group, members in grouped(self.parameters.values()):
            if group:
                header = group_header(group)
                self.layout_.addRow(header)
                self.headers[group] = (header, [p.name for p in members])
            for parameter in members:
                self._add(parameter)
        self.show_used()

    def _add(self, parameter: ParameterInfo) -> None:
        editor = make_editor(parameter)
        if parameter.default is not None and not parameter.required:
            editor.set(parameter.default)
        if parameter.help:
            editor.widget.setToolTip(parameter.help)
        label = QLabel(parameter.label)
        label.setToolTip(parameter.name)
        self.layout_.addRow(label, editor.widget)
        self.editors[parameter.name] = editor
        self._watch(editor.widget)

    def shown(self, name: str) -> bool:
        """Whether the parameter's row is shown: its conditions hold."""
        return self.layout_.isRowVisible(self.editors[name].widget)

    def show_used(self) -> None:
        """Rows of the parameters whose conditions hold, and the lines of
        groups with any of them."""
        deciding = {
            condition.parameter
            for parameter in self.parameters.values()
            for condition in parameter.shown_if
        }
        values = {}
        for name in deciding & set(self.editors):
            try:
                values[name] = self.editors[name].get()
            except ValueError:
                continue  # typed text that is not numbers: what it decides is hidden
        for name, parameter in self.parameters.items():
            self.layout_.setRowVisible(
                self.editors[name].widget, parameter.shown(values)
            )
        for header, names in self.headers.values():
            self.layout_.setRowVisible(header, any(map(self.shown, names)))

    def _watch(self, widget: QWidget) -> None:
        for child in [widget, *widget.findChildren(QWidget)]:
            if isinstance(child, QCheckBox):
                child.toggled.connect(self.changed)
            elif isinstance(child, QComboBox):
                child.currentIndexChanged.connect(self.changed)
            elif isinstance(child, (QSpinBox, QDoubleSpinBox, QLineEdit)):
                child.editingFinished.connect(self.changed)

    def values(self) -> Dict[str, Any]:
        """SI values as JSON; raises ValueError naming every field whose text
        is not numbers."""
        values, problems = {}, []
        for name, editor in self.editors.items():
            try:
                values[name] = editor.get()
            except ValueError as e:
                problems.append(f"{self.parameters[name].label}: {e}")
        if problems:
            raise ValueError("; ".join(problems))
        return values

    def widget(self, name: str) -> Optional[QWidget]:
        editor = self.editors.get(name)
        return editor.widget if editor is not None else None

    def typed(self, name: str) -> str:
        """A parameter's value as people type it, in its display unit; the
        problem, for text that is not numbers."""
        try:
            return self.parameters[name].typed(self.editors[name].get())
        except ValueError as e:
            return f"{e}"

    def set_values(self, values: Mapping[str, Any]) -> None:
        for name, value in values.items():
            if name in self.editors:
                try:
                    self.editors[name].set(value)
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass  # a value saved by an older version: the editor keeps its own
        self.show_used()


def saved_or_told(dialog: QDialog, title: str, save: Callable[[], None]) -> None:
    """Save what a dialog holds and close it; a value that is not a number, or a
    refusal of the lab, is told and the dialog stays."""
    try:
        save()
    except (ValueError, LabError) as e:
        QMessageBox.warning(dialog, title, str(e))
        return
    dialog.accept()


class DeviceSlotsForm(QWidget):
    """Which device of the bench plays each procedure slot; only suitable devices are listed."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QFormLayout(self)
        self.combos: Dict[str, QComboBox] = {}
        self.slots: Dict[str, SlotInfo] = {}

    def set_slots(
        self,
        slots: Sequence[SlotInfo],
        devices: Sequence[DeviceInfo],
        preferred: Optional[Mapping[str, str]] = None,
    ) -> None:
        current = {**(preferred or {}), **self.mapping()}
        while self.layout_.rowCount():
            self.layout_.removeRow(0)
        self.combos.clear()
        self.slots = {slot.name: slot for slot in slots}
        # Devices chosen before are kept; free slots take the next unused device
        taken = {current[name] for name in self.slots if current.get(name)}
        for slot in slots:
            combo = compact_combo(QComboBox(), 14)
            for info in slot.candidates(devices):
                combo.addItem(info.title, info.ref)
                combo.setItemData(combo.count() - 1, info.ref, Qt.ToolTipRole)
            wanted = current.get(slot.name, slot.name)
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
            combo.setToolTip(" + ".join(slot.capabilities) or "any device")
            combo.currentIndexChanged.connect(self.changed)
            self.layout_.addRow(slot.title, combo)
            self.combos[slot.name] = combo
        self.changed.emit()

    def mapping(self) -> Dict[str, str]:
        return {
            slot: combo.currentData()
            for slot, combo in self.combos.items()
            if combo.currentData()
        }

    def widget(self, slot: str) -> Optional[QWidget]:
        return self.combos.get(slot)

    def choices(self, slot: str) -> Tuple[str, ...]:
        """The devices that suit a slot, by ref."""
        combo = self.combos[slot]
        return tuple(combo.itemData(i) for i in range(combo.count()))

    def choose(self, slot: str, ref: str) -> bool:
        """This device for the slot; False when it has no such slot or the
        device does not suit it."""
        combo = self.combos.get(slot)
        index = combo.findData(ref) if combo is not None else -1
        if index >= 0:
            combo.setCurrentIndex(index)
        return index >= 0

    def unmapped(self) -> List[SlotInfo]:
        return [
            self.slots[name]
            for name, combo in self.combos.items()
            if not combo.currentData()
        ]

    def summary(self) -> str:
        """One line for the folded group: SIS bias: SIS1 · Detector: R&S NRX."""
        return " · ".join(
            f"{self.slots[name].title}: {combo.currentText() or '—'}"
            for name, combo in self.combos.items()
        )
