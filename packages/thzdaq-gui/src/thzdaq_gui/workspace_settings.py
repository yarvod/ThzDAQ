"""The settings of the window's workspace (File → Workspace settings): the
Python its scripts, measurements of the bench's own and consoles run with.

The environments found (the program's own, the workspace's .venv, uv's and
conda's) are offered, Browse… adds any interpreter, and the one chosen is
checked (InterpreterModel): its Python and thzdaq, with what mends a
problem. Save writes it into thzdaq.toml, even one that fails its check (a
person may install thzdaq there next); consoles that run keep theirs until
their Restart.
"""

import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QToolButton,
)
from thzdaq_api.errors import LabError
from thzdaq_api.interpreters import CHOSEN, Checked, Environment, located

from thzdaq_gui import theme

TITLE = "Workspace settings"
LOOKING = "Looking for environments…"
NONE_FOUND = "None found"
CHECKING = "Checking…"
KEPT_UNTIL_RESTART = (
    "Consoles that run keep their Python until their Restart; scripts, "
    "measurements and new consoles take the one saved here."
)
WIDTH = 48  # characters the choice of a Python shows
DIALOG_WIDTH = 680
INTERPRETERS = "Python (python.exe)" if sys.platform == "win32" else "Python (python*)"


class WorkspaceSettings(QDialog):
    def __init__(self, model, parent=None):
        """model: the window's InterpreterModel."""
        super().__init__(parent)
        self.model = model
        self.setWindowTitle(f"{TITLE}: {model.workspace.name}")
        self.choices = QComboBox()
        self.choices.setObjectName("pythons")
        # A long path among them does not widen the dialog
        self.choices.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.choices.setMinimumContentsLength(WIDTH)
        self.choices.addItem(LOOKING)
        self.choices.setEnabled(False)
        self.browse = QToolButton()
        self.browse.setIcon(theme.icon("folder-open-outline"))
        self.browse.setToolTip("Any Python: an interpreter of your own")
        self.browse.clicked.connect(self.choose_file)
        which = QHBoxLayout()
        which.addWidget(self.choices, 1)
        which.addWidget(self.browse)
        self.path = self._shown("")  # the chosen one's folder
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.remedy = self._shown("")  # a command to copy: paths do not wrap
        note = QLabel(KEPT_UNTIL_RESTART)
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED}")
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.form = QFormLayout(self)
        self.form.addRow("Folder", self._shown(str(model.workspace.folder)))
        self.form.addRow("Python", which)
        self.form.addRow("", self.path)
        self.form.addRow("Check", self.result)
        self.form.addRow("Mend", self.remedy)
        self.form.setRowVisible(self.remedy, False)
        self.form.addRow(note)
        self.form.addRow(self.buttons)
        self.resize(DIALOG_WIDTH, self.sizeHint().height())
        self.choices.setFocus()
        model.found.connect(self._found)
        model.checked.connect(self._checked)
        model.failed.connect(self._failed)
        self.choices.currentIndexChanged.connect(self._chosen)
        model.find()

    @staticmethod
    def _shown(text: str) -> QLineEdit:
        """A path or a command, read and copied, not typed: it scrolls."""
        shown = QLineEdit(text)
        shown.setReadOnly(True)
        shown.setFocusPolicy(Qt.ClickFocus)  # Tab goes to what is chosen
        shown.setCursorPosition(0)
        return shown

    def chosen(self) -> Optional[Environment]:
        found = self.choices.currentData()
        return found if isinstance(found, Environment) else None

    def _found(self, found, current: Optional[Environment]) -> None:
        self.choices.blockSignals(True)
        self.choices.clear()
        for environment in found:
            self._add(environment)
        self.choices.setCurrentIndex(found.index(current) if current in found else 0)
        self.choices.setEnabled(True)
        self.choices.blockSignals(False)
        self._chosen()  # checked once

    def _add(self, environment: Environment) -> None:
        self.choices.addItem(f"{environment.kind}: {environment.name}", environment)
        self.choices.setItemData(
            self.choices.count() - 1, environment.path, Qt.ToolTipRole
        )

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Python of the workspace", str(self.model.workspace.folder),
            INTERPRETERS,
        )  # fmt: skip
        if path:
            self.add_python(path)

    def add_python(self, path: str) -> None:
        """An interpreter of a person's own among the choices, chosen."""
        interpreter = located(path)
        for index in range(self.choices.count()):
            environment = self.choices.itemData(index)
            if isinstance(environment, Environment) and environment.runs(interpreter):
                self.choices.setCurrentIndex(index)
                return
        self._add(Environment(CHOSEN, str(interpreter), str(interpreter)))
        self.choices.setCurrentIndex(self.choices.count() - 1)

    def _chosen(self, *_) -> None:
        environment = self.chosen()
        if environment is None:
            return
        self.path.setText(environment.path or "Built into the program")
        self.path.setCursorPosition(0)
        self._show(CHECKING, theme.MUTED)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(True)
        self.model.check(environment)

    def _checked(self, environment: Environment, checked: Checked) -> None:
        if environment != self.chosen():
            return  # asked of a choice left since
        self._show(checked.summary(), theme.GOOD if checked.ok else theme.BAD)
        self.remedy.setText(checked.remedy())
        self.remedy.setCursorPosition(0)
        self.form.setRowVisible(self.remedy, bool(checked.remedy()))

    def _show(self, text: str, color: str) -> None:
        """The check's summary; what mends it is hidden until it is told."""
        self.result.setText(text)
        self.result.setStyleSheet(f"color: {color}")
        self.form.setRowVisible(self.remedy, False)

    def _failed(self, why: str) -> None:
        if not self.choices.isEnabled():  # finding them failed
            self.choices.setItemText(0, NONE_FOUND)
        self._show(why, theme.BAD)

    def accept(self) -> None:
        environment = self.chosen()
        if environment is None:
            return
        try:
            self.model.choose(environment)
        except LabError as e:
            QMessageBox.warning(self, TITLE, str(e))
            return
        super().accept()
