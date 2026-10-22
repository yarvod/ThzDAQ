"""Mouse wheel changes a spin box or combo box only after it was clicked (focused).

Without this, scrolling a dock over a setpoint field silently changes the
value. The guard is an application event filter, so every field (Qt and
pyqtgraph spin boxes) is covered; the wheel then scrolls the dock instead.
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
)

GUARDED = (QAbstractSpinBox, QComboBox)


class WheelGuard(QObject):
    def eventFilter(self, obj, event) -> bool:
        if not isinstance(obj, GUARDED):
            return False
        if event.type() == QEvent.Polish:
            # Qt gives WheelFocus widgets the focus on a wheel turn, before any
            # filter: focus by click or Tab only
            if obj.focusPolicy() == Qt.WheelFocus:
                obj.setFocusPolicy(Qt.StrongFocus)
            return False
        if event.type() != QEvent.Wheel or obj.hasFocus():
            return False
        # Not ours: the scroll area around the field (a dock) scrolls instead
        parent = obj.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            QApplication.sendEvent(parent.viewport(), event)
        return True


_guard = None


def install(app: QApplication) -> None:
    global _guard
    if _guard is None:
        _guard = WheelGuard(app)
        app.installEventFilter(_guard)
