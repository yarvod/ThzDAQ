"""Perspectives: named dock layouts of Pro (SIS tuning, 2SB noise, ...).

Chosen and edited in the toolbar; ADS keeps them, they are saved in the
settings with the one in use.
"""

from typing import List, Optional

from PySide6.QtCore import QSettings, QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QToolBar,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.docking import DockSpace, one_repaint

DEFAULT = "Default"
SAVED = "Perspectives"  # the settings array ADS writes
CURRENT_KEY = "perspective"


class Perspectives:
    def __init__(self, docks: DockSpace, settings: QSettings, window: QWidget):
        self.docks = docks
        self.manager = docks.manager
        self.settings = settings
        self.window = window  # parent of the dialogs, repainted once per switch
        self.current: Optional[str] = None
        self.combo = QComboBox()
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.combo.setToolTip("Perspective: a saved layout of docks")
        self.combo.textActivated.connect(self.open)
        self.actions: List[QAction] = []  # in the toolbar, shown in Pro only

    def add_to(self, toolbar: QToolBar) -> None:
        label = QLabel(" Perspective ")
        label.setProperty("role", "muted")
        self.actions = [toolbar.addWidget(label), toolbar.addWidget(self.combo)]
        for icon_name, tip, slot in (
            ("view-grid-plus-outline", "Create perspective", self.create),
            ("content-save-outline", "Update current perspective", self.update),
            ("rename-outline", "Rename current perspective", self.rename),
            ("delete-outline", "Delete current perspective", self.delete),
        ):
            action = toolbar.addAction(theme.icon(icon_name), tip)
            action.triggered.connect(slot)
            self.actions.append(action)

    def set_visible(self, on: bool) -> None:
        for action in self.actions:
            action.setVisible(on)

    def refresh(self) -> None:
        with QSignalBlocker(self.combo):
            self.combo.clear()
            self.combo.addItems(self.manager.perspectiveNames())
            if self.current:
                self.combo.setCurrentText(self.current)

    def open(self, name: str) -> None:
        if not name:
            return
        with one_repaint(self.window):
            self.manager.openPerspective(name)
            self.docks.sync_bodies()
        self.current = name

    def create(self) -> None:
        name, ok = QInputDialog.getText(
            self.window, "Create perspective", "Unique name"
        )
        if ok and name.strip():
            self.manager.addPerspective(name.strip())
            self.current = name.strip()
            self.refresh()
            self.save()

    def update(self) -> None:
        name = self.combo.currentText()
        if name:
            self.manager.addPerspective(name)
            self.save()

    def delete(self) -> None:
        name = self.combo.currentText()
        if not name:
            return
        answer = QMessageBox.question(
            self.window, "Delete perspective", f"Delete perspective {name!r}?"
        )
        if answer == QMessageBox.Yes:
            self.manager.removePerspective(name)
            self.current = None
            self.refresh()
            self.save()

    def rename(self) -> None:
        old = self.combo.currentText()
        if not old:
            return
        name, ok = QInputDialog.getText(
            self.window, "Rename perspective", "New name", text=old
        )
        name = name.strip()
        if not ok or not name or name == old:
            return
        if name in self.manager.perspectiveNames():
            QMessageBox.warning(self.window, "Rename perspective", f"{name!r} exists")
            return
        # ADS cannot rename: the saved list is read back with the new name
        self.save()
        count = self.settings.beginReadArray(SAVED)
        saved = []
        for i in range(count):
            self.settings.setArrayIndex(i)
            saved.append((self.settings.value("Name"), self.settings.value("State")))
        self.settings.endArray()
        self.settings.remove(SAVED)
        self.settings.beginWriteArray(SAVED, len(saved))
        for i, (key, state) in enumerate(saved):
            self.settings.setArrayIndex(i)
            self.settings.setValue("Name", name if key == old else key)
            self.settings.setValue("State", state)
        self.settings.endArray()
        self.settings.sync()
        self.manager.loadPerspectives(self.settings)
        self.current = name
        self.refresh()

    def add_default(self) -> None:
        """The first layout of Pro, as the Default perspective."""
        if DEFAULT not in self.manager.perspectiveNames():
            self.manager.addPerspective(DEFAULT)
            self.current = DEFAULT

    def load(self) -> None:
        self.manager.loadPerspectives(self.settings)
        self.current = self.settings.value(CURRENT_KEY) or None

    def save(self) -> None:
        self.settings.remove(SAVED)
        self.manager.savePerspectives(self.settings)
        self.settings.setValue(CURRENT_KEY, self.current or "")
        self.settings.sync()
