"""Forms built from procedure parameters and role requirements.

Editors show display units (GHz, mV); values() returns SI values ready for
Procedure(**values).
"""

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple, Type

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.parameters import Parameter, Sweep
from thzdaq_core.measurements.procedure import Procedure

LIMIT = 1e15


def to_si(value: float, scale: float) -> float:
    """Display value -> SI, without 2.6 mV turning into 0.0026000000000000003 V."""
    return float(f"{value * scale:.12g}")


def _double_spin(parameter: Parameter) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
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
        spin = QSpinBox()
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
        points = QSpinBox()
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
    """Form of a procedure class; empty until set_procedure()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QFormLayout(self)
        self.procedure_class: Optional[Type[Procedure]] = None
        self.editors: Dict[str, Editor] = {}

    def set_procedure(self, procedure_class: Type[Procedure]) -> None:
        while self.layout_.rowCount():
            self.layout_.removeRow(0)
        self.editors.clear()
        self.procedure_class = procedure_class
        for name, parameter in procedure_class.parameters().items():
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

    def values(self) -> Dict[str, Any]:
        """SI values; raises ProcedureError listing every invalid field."""
        values, problems = {}, []
        parameters = self.procedure_class.parameters()
        for name, editor in self.editors.items():
            try:
                values[name] = parameters[name].validate(editor.get())
            except ProcedureError as e:
                problems.append(f"{parameters[name].label}: {e}")
        if problems:
            raise ProcedureError("; ".join(problems))
        return values

    def set_values(self, values: Mapping[str, Any]) -> None:
        for name, value in values.items():
            if name in self.editors:
                self.editors[name].set(value)

    def procedure(self) -> Procedure:
        procedure = self.procedure_class(**self.values())
        procedure.validate()
        return procedure


class RoleMappingForm(QWidget):
    """Procedure role -> station role, defaulting to the same name."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QFormLayout(self)
        self.combos: Dict[str, QComboBox] = {}

    def set_roles(
        self, required: Mapping[str, Any], station_roles: Iterable[str]
    ) -> None:
        current = self.mapping()
        while self.layout_.rowCount():
            self.layout_.removeRow(0)
        self.combos.clear()
        station_roles = list(station_roles)
        for role, capabilities in required.items():
            combo = QComboBox()
            combo.addItems(station_roles)
            wanted = current.get(role, role)
            if wanted in station_roles:
                combo.setCurrentText(wanted)
            else:
                combo.setCurrentIndex(-1)
            caps = capabilities if isinstance(capabilities, tuple) else (capabilities,)
            combo.setToolTip(" + ".join(c.__name__ for c in caps))
            self.layout_.addRow(role, combo)
            self.combos[role] = combo

    def mapping(self) -> Dict[str, str]:
        return {
            role: combo.currentText()
            for role, combo in self.combos.items()
            if combo.currentText()
        }

    def unmapped(self) -> List[str]:
        return [role for role, combo in self.combos.items() if not combo.currentText()]


def summarize_capabilities(capabilities) -> Tuple[str, ...]:
    caps = capabilities if isinstance(capabilities, tuple) else (capabilities,)
    return tuple(c.__name__ for c in caps)
