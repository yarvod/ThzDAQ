"""A section that folds to its title line, with a short summary while folded.

Folded or not is remembered by key (the same for all docks of a procedure),
so a scan folded in one SIS bias dock is folded in the others too.
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.settings import settings

KEY = "sections/{}"


class Collapsible(QWidget):
    toggled = Signal(bool)  # expanded

    def __init__(
        self,
        title: str,
        key: Optional[str] = None,
        expanded: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.key = KEY.format(key) if key else None
        if self.key is not None:
            saved = settings().value(self.key)
            if saved is not None:
                expanded = str(saved).lower() == "true"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(2)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.button = QToolButton()
        self.button.setCheckable(True)
        self.button.setChecked(expanded)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setText(title)
        self.button.setStyleSheet(
            f"QToolButton {{ color: {theme.ACCENT}; font-weight: bold; border: none; "
            "padding: 1px 2px; } "
            f"QToolButton:hover {{ color: #ffb33d; background: transparent; }}"
            "QToolButton:checked { background: transparent; }"
        )
        self.button.toggled.connect(self.set_expanded)
        header.addWidget(self.button)
        self.summary = QLabel()
        self.summary.setProperty("role", "muted")
        # A long summary is cut, it never widens the dock
        self.summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.summary.setMinimumWidth(0)
        header.addWidget(self.summary, 1)
        header.addStretch()  # the title on the left while the summary is hidden
        layout.addLayout(header)
        self.body = QFrame()
        self.body.setObjectName("collapsibleBody")
        self.body.setStyleSheet(
            f"#collapsibleBody {{ border-left: 1px solid {theme.BORDER}; }}"
        )
        self.content_layout = QVBoxLayout(self.body)
        self.content_layout.setContentsMargins(8, 2, 0, 2)
        layout.addWidget(self.body)
        self.set_expanded(expanded, remember=False)

    def addWidget(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)

    def setTitle(self, title: str) -> None:
        self.button.setText(title)

    def title(self) -> str:
        return self.button.text()

    def expanded(self) -> bool:
        return self.button.isChecked()

    def set_expanded(self, on: bool, remember: bool = True) -> None:
        if self.button.isChecked() != on:
            self.button.setChecked(on)  # comes back here through toggled
            return
        self.button.setIcon(theme.icon("chevron-down" if on else "chevron-right"))
        self.body.setVisible(on)
        self.summary.setVisible(not on and bool(self.summary.text()))
        if remember and self.key is not None:
            settings().setValue(self.key, on)
        self.toggled.emit(on)

    def set_summary(self, text: str) -> None:
        """What the folded section says on its title line."""
        self.summary.setText(text)
        self.summary.setToolTip(text)
        self.summary.setVisible(not self.expanded() and bool(text))
