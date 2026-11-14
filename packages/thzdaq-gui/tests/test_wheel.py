import pyqtgraph as pg
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def turn_wheel(widget, steps: int = 1) -> None:
    center = QPointF(widget.rect().center())
    event = QWheelEvent(
        center, widget.mapToGlobal(center), QPoint(), QPoint(0, 120 * steps),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )  # fmt: skip
    QApplication.sendEvent(widget, event)


@pytest.fixture
def fields(app):
    area = QScrollArea()
    inner = QWidget()
    layout = QVBoxLayout(inner)
    double, integer, combo = QDoubleSpinBox(), QSpinBox(), QComboBox()
    graph_spin = pg.SpinBox(value=1.0)
    combo.addItems(["a", "b", "c"])
    for widget in (double, integer, combo, graph_spin):
        layout.addWidget(widget)
    layout.addSpacing(2000)  # something to scroll
    area.setWidget(inner)
    area.setWidgetResizable(True)
    area.resize(300, 200)
    area.show()
    app.processEvents()
    yield area, double, integer, combo, graph_spin
    area.close()


def test_hover_with_the_wheel_changes_nothing(app, fields):
    area, double, integer, combo, graph_spin = fields
    for widget in (double, integer, combo, graph_spin):
        assert widget.focusPolicy() != Qt.WheelFocus
        turn_wheel(widget, -1)
    app.processEvents()
    assert double.value() == 0 and integer.value() == 0
    assert combo.currentIndex() == 0 and graph_spin.value() == 1.0
    # The wheel went to the scroll area instead
    assert area.verticalScrollBar().value() > 0


def test_a_focused_field_takes_the_wheel(app, fields):
    area, double, integer, combo, graph_spin = fields
    area.activateWindow()
    integer.setFocus()
    app.processEvents()
    if not integer.hasFocus():
        pytest.skip("no window focus on this platform")
    turn_wheel(integer, 1)
    assert integer.value() == 1
