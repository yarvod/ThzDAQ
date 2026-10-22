"""Dark theme with orange accents (Fusion palette + style sheets) and icons.

The dock manager takes its colors from the palette: the focused dock tab and
title bar use palette(highlight), so the whole application follows ACCENT.
Icons are Material Design icons from qtawesome, tinted for the dark theme.
"""

from pathlib import Path

import pyqtgraph as pg
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#f39c12"
ACCENT_DARK = "#c77c02"
WINDOW = "#2b2b2b"
BASE = "#1f1f1f"
PANEL = "#333333"
TEXT = "#e6e6e6"
MUTED = "#9a9a9a"
BORDER = "#444444"
PLOT_BACKGROUND = "#151515"

# Curves on the dark plots: accent first, then distinct colors
COLORS = (
    "#f39c12", "#4fc3f7", "#81c784", "#e57373", "#ba68c8",
    "#ffd54f", "#4db6ac", "#f06292", "#aed581", "#90a4ae",
)  # fmt: skip

RESOURCES = Path(__file__).parent / "resources"

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
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {BASE}; border: 1px solid {BORDER}; border-radius: 3px; padding: 2px 4px;
    selection-background-color: {ACCENT}; selection-color: #111;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; selection-background-color: {ACCENT}; }}
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
    app.setStyleSheet(STYLE)
    pg.setConfigOptions(antialias=True, background=PLOT_BACKGROUND, foreground=TEXT)
    from thzdaq_gui import wheel

    wheel.install(app)


def dock_style_sheet() -> str:
    return (RESOURCES / "docks.css").read_text(encoding="utf-8")


def icon(name: str, color: str = TEXT, active: str = ACCENT) -> QIcon:
    """mdi6 icon by name, e.g. icon("chart-line"); empty icon if unavailable."""
    try:
        import qtawesome as qta

        # A copy: qtawesome caches icons, and widgets may take ownership of theirs
        return QIcon(qta.icon(f"mdi6.{name}", color=color, color_active=active))
    except Exception:
        return QIcon()


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
    name = DEVICE_ICONS.get(kind)
    if name is None:
        prefix = instrument_id.rsplit("_", 1)[0]
        name = DEVICE_ICONS.get(prefix, "chip")
    return icon(name)
