"""Dark theme with orange accents (Fusion palette + style sheets) and icons.

The dock manager takes its colors from the palette: the focused dock tab and
title bar use palette(highlight), so the whole application follows ACCENT.
Icons are Material Design icons from qtawesome, tinted for the dark theme.
"""

from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSpinBox, QToolButton

from thzdaq_gui.device_types import id_type

ACCENT = "#f39c12"
ACCENT_DARK = "#c77c02"
WINDOW = "#2b2b2b"
BASE = "#1f1f1f"
PANEL = "#333333"
TEXT = "#e6e6e6"
MUTED = "#9a9a9a"
BORDER = "#444444"
GOOD = "#81c784"  # connected, completed
BAD = "#e57373"  # an error, no connection
PLOT_BACKGROUND = "#151515"

# Curves on the dark plots: accent first, then distinct colors
COLORS = (
    "#f39c12", "#4fc3f7", "#81c784", "#e57373", "#ba68c8",
    "#ffd54f", "#4db6ac", "#f06292", "#aed581", "#90a4ae",
)  # fmt: skip

RESOURCES = Path(__file__).parent / "resources"
# Arrows of spin and combo boxes in TEXT, ACCENT (hover) and MUTED (disabled):
# Fusion draws its own a few pixels wide once a style sheet styles the box
ARROWS = (RESOURCES / "arrows").as_posix()

# Fields as tall as buttons, 28 px: content + padding + border.
FIELD_HEIGHT = 20
STEP_WIDTH = 18  # the up/down buttons of a spin box, the arrow of a combo box

STYLE = f"""
QWidget {{ font-size: 10pt; }}
QToolTip {{ color: {TEXT}; background: {PANEL}; border: 1px solid {ACCENT}; }}
QMenuBar {{ background: {WINDOW}; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {ACCENT}; color: #111; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QToolBar {{ background: {WINDOW}; border: none; spacing: 4px; padding: 2px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 3px; padding: 3px; }}
QToolButton:hover {{ border-color: {ACCENT}; background: {PANEL}; }}
QToolButton:checked {{ border-color: {ACCENT}; background: #4a3a1c; }}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 4px; margin-top: 14px; padding-top: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {ACCENT}; font-weight: bold;
}}
QPushButton {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 3px;
    padding: 4px 10px; min-height: 18px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT_DARK}; color: #111; }}
QPushButton:checked {{ background: {ACCENT}; color: #111; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: #3a3a3a; }}
QPushButton[accent="true"] {{ background: {ACCENT}; color: #111; border-color: {ACCENT}; }}
QPushButton[accent="true"]:hover {{ background: #ffb33d; }}
QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {BASE}; border: 1px solid {BORDER}; border-radius: 3px; padding: 2px 6px;
    selection-background-color: {ACCENT}; selection-color: #111;
}}
QLineEdit, QComboBox {{
    min-height: {FIELD_HEIGHT}px; padding-top: 3px; padding-bottom: 3px;
}}
QAbstractSpinBox {{
    min-height: $spin_heightpx; padding-top: 0; padding-bottom: 0; padding-right: 2px;
}}
QAbstractSpinBox QLineEdit {{
    background: transparent; border: none; padding: 0; min-height: 0;
}}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {{
    color: {MUTED}; border-color: #3a3a3a;
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: padding; width: {STEP_WIDTH}px;
    background: {PANEL}; border-left: 1px solid {BORDER};
}}
QAbstractSpinBox::up-button {{
    subcontrol-position: top right; border-top-right-radius: 2px;
    border-bottom: 1px solid {BORDER};
}}
QAbstractSpinBox::down-button {{
    subcontrol-position: bottom right; border-bottom-right-radius: 2px;
}}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
    background: #3d3d3d;
}}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{
    background: #4a3a1c;
}}
QAbstractSpinBox::up-arrow {{ image: url("{ARROWS}/up-normal.svg"); width: 10px; height: 6px; }}
QAbstractSpinBox::up-arrow:hover, QAbstractSpinBox::up-arrow:pressed {{
    image: url("{ARROWS}/up-hover.svg");
}}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{
    image: url("{ARROWS}/up-disabled.svg");
}}
QAbstractSpinBox::down-arrow {{
    image: url("{ARROWS}/down-normal.svg"); width: 10px; height: 6px;
}}
QAbstractSpinBox::down-arrow:hover, QAbstractSpinBox::down-arrow:pressed {{
    image: url("{ARROWS}/down-hover.svg");
}}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{
    image: url("{ARROWS}/down-disabled.svg");
}}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: top right; width: {STEP_WIDTH}px;
    border-left: 1px solid {BORDER}; border-top-right-radius: 2px;
    border-bottom-right-radius: 2px; background: {PANEL};
}}
QComboBox::drop-down:hover {{ background: #3d3d3d; }}
QComboBox::down-arrow {{ image: url("{ARROWS}/down-normal.svg"); width: 10px; height: 6px; }}
QComboBox::down-arrow:hover, QComboBox::down-arrow:on {{
    image: url("{ARROWS}/down-hover.svg");
}}
QComboBox::down-arrow:disabled {{ image: url("{ARROWS}/down-disabled.svg"); }}
QAbstractItemView QLineEdit, QAbstractItemView QAbstractSpinBox,
QAbstractItemView QComboBox {{ min-height: 0; padding-top: 0; padding-bottom: 0; }}
QComboBox QAbstractItemView {{ background: {PANEL}; selection-background-color: {ACCENT}; }}
QDoubleSpinBox[pending="true"], QComboBox[pending="true"] {{ border: 1px solid {ACCENT}; }}
QProgressBar {{
    border: 1px solid {BORDER}; border-radius: 3px; background: {BASE};
    text-align: center; min-height: 16px;
}}
QProgressBar::chunk {{ background: {ACCENT}; }}
QHeaderView::section {{
    background: {PANEL}; color: {TEXT}; border: none;
    border-right: 1px solid {BORDER}; border-bottom: 2px solid {ACCENT}; padding: 4px;
}}
QTableView, QTreeView, QListView {{
    background: {BASE}; alternate-background-color: #262626; gridline-color: {BORDER};
    selection-background-color: {ACCENT}; selection-color: #111; border: 1px solid {BORDER};
}}
QTabBar::tab {{ background: {PANEL}; padding: 5px 10px; border: 1px solid {BORDER}; }}
QTabBar::tab:selected {{ background: {WINDOW}; border-bottom: 2px solid {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
QCheckBox::indicator {{
    width: 13px; height: 13px; border: 1px solid {MUTED}; border-radius: 2px; background: {BASE};
}}
QAbstractItemView::indicator {{
    width: 13px; height: 13px; border: 1px solid {MUTED}; border-radius: 2px; background: {BASE};
}}
QAbstractItemView::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QStatusBar {{ background: {WINDOW}; border-top: 1px solid {BORDER}; }}
QLabel[role="value"] {{ color: {ACCENT}; font-size: 13pt; }}
QLabel[role="title"] {{ color: {ACCENT}; font-size: 13pt; font-weight: bold; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QScrollArea {{ border: none; }}
QToolButton[select="true"] {{
    background: {BASE}; border: 1px solid {BORDER}; border-radius: 3px;
    min-height: {FIELD_HEIGHT}px; padding: 3px 22px 3px 6px;
}}
QToolButton[select="true"]:hover, QToolButton[select="true"]:open {{
    border-color: {ACCENT};
}}
QToolButton[select="true"]::menu-indicator {{
    image: url("{ARROWS}/down-normal.svg"); width: 10px; height: 6px;
    subcontrol-origin: padding; subcontrol-position: center right; right: 6px;
}}
"""


def palette() -> QPalette:
    p = QPalette()
    colors = {
        QPalette.Window: WINDOW,
        QPalette.WindowText: TEXT,
        QPalette.Base: BASE,
        QPalette.AlternateBase: "#262626",
        QPalette.ToolTipBase: PANEL,
        QPalette.ToolTipText: TEXT,
        QPalette.Text: TEXT,
        QPalette.Button: PANEL,
        QPalette.ButtonText: TEXT,
        QPalette.BrightText: "#ffffff",
        QPalette.Highlight: ACCENT,
        QPalette.HighlightedText: "#111111",
        QPalette.Link: ACCENT,
        QPalette.Light: "#4a4a4a",
        QPalette.Midlight: "#3c3c3c",
        QPalette.Mid: "#303030",
        QPalette.Dark: "#1b1b1b",
        QPalette.Shadow: "#000000",
        QPalette.PlaceholderText: MUTED,
    }
    for role, color in colors.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(MUTED))
    return p


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(palette())
    option = QStyleOptionSpinBox()
    option.frame = True
    # Qt adds the native spin-box frame as well as the stylesheet's border;
    # its size varies by platform, even with Fusion.
    frame = (
        app.style().sizeFromContents(QStyle.CT_SpinBox, option, QSize(0, 0)).height()
    )
    app.setStyleSheet(STYLE.replace("$spin_height", str(FIELD_HEIGHT + 6 - frame)))
    pg.setConfigOptions(antialias=True, background=PLOT_BACKGROUND, foreground=TEXT)
    import qtawesome as qta

    # qtawesome keeps every icon it made in a QObject of its module: Python
    # frees them at its exit, after the application, and a QIcon freed then
    # crashes it (SIGBUS in the destructor). They go while the application lives.
    app.aboutToQuit.connect(qta.reset_cache)
    from thzdaq_gui import wheel

    wheel.install(app)


def dock_style_sheet() -> str:
    return (RESOURCES / "docks.css").read_text(encoding="utf-8")


APP_ICON_SIZES = (16, 32, 48, 64, 128, 256)


def app_icon() -> QIcon:
    """The ThzDAQ pixel icon, one hand-drawn picture per size (assets/make_icon.py)."""
    result = QIcon()
    for size in APP_ICON_SIZES:
        result.addFile(str(RESOURCES / "icon" / f"thzdaq_{size}.png"))
    return result


def icon(name: str, color: str = TEXT, active: str = ACCENT) -> QIcon:
    """mdi6 icon by name, e.g. icon("chart-line"); empty icon if unavailable."""
    try:
        import qtawesome as qta

        # A copy: qtawesome caches icons, and widgets may take ownership of theirs
        return QIcon(qta.icon(f"mdi6.{name}", color=color, color_active=active))
    except Exception:
        return QIcon()


def tool_button(text: str, name: str, tip: str, slot) -> QToolButton:
    """A button of a tab's toolbar row: its icon with its text beside it."""
    button = QToolButton()
    button.setText(text)
    button.setIcon(icon(name))
    button.setToolTip(tip)
    button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    button.clicked.connect(slot)
    return button


class Spinner:
    """A turning icon for what goes on now, in one widget that paints it (a
    menu, a button): qtawesome turns it by repainting that widget on a timer
    of its own, made at the icon's first paint. The timer runs only while
    the icon is shown: run(False) once nothing shows it."""

    def __init__(self, widget):
        import qtawesome as qta

        self.animation = qta.Spin(widget, interval=40, step=12)
        self.icon = QIcon(
            qta.icon("mdi6.loading", color=ACCENT, animation=self.animation)
        )

    def run(self, on: bool) -> None:
        if on:
            self.animation.start()
        else:
            self.animation.stop()


# Icons by device kind or capability, for docks, menus and lists
DEVICE_ICONS = {
    "sis_bias": "alpha-s-box-outline",
    "sis_coil": "magnet",
    "sis_block": "chip",
    "power_supply": "power-plug-outline",
    "signal_generator": "sine-wave",
    "frequency_multiplier": "sine-wave",
    "power_meter": "gauge",
    "spectrum_analyzer": "chart-bell-curve",
    "vna": "radar",
    "temperature_controller": "thermometer",
    "compressor": "snowflake",
    "chopper": "fan",
    "yig_filter": "filter-outline",
    "grid": "rotate-3d-variant",
    "sideband_selector": "toggle-switch-outline",
    "switch": "toggle-switch-outline",
    "vacuum": "gauge-low",
}


def device_icon(kind: str, instrument_id: str = "") -> QIcon:
    """By the device's kind, an instrument by the type its id names."""
    name = DEVICE_ICONS.get(kind) or DEVICE_ICONS.get(id_type(instrument_id), "chip")
    return icon(name)
