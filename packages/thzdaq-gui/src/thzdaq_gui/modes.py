"""Lite and Pro, the two ways of working: the window asks its mode what differs.

Pro: a dock per measurement and perspectives (saved layouts). Lite: one
layout; the measurement chosen in the bar on top runs from there, its setup
in the Measurement dock. Each mode keeps its own layout.
"""

from typing import Mapping, Optional, Tuple

import PySide6QtAds as QtAds
from PySide6.QtCore import QSettings

from thzdaq_gui.dock_names import MEASURE, MEASUREMENT, dock_name, key_of
from thzdaq_gui.runbar import MeasurementHost, RunBar

MODE_KEY = "ui/mode"
CHOSEN_KEY = "ui/measurement"
DEFAULT_MEASUREMENT = "sis.iv_curve"


class Mode:
    key = ""
    title = ""
    tip = ""
    state_key = ""  # where its layout is saved
    perspectives = False  # saved layouts in the toolbar
    run_bar = False  # the bar on top runs the chosen measurement
    measure_column: Tuple[str, ...] = ()  # on the right in a default layout

    def enter(self) -> None:
        """Its layout is restored or made: settle its docks."""

    def leave(self) -> None:
        """The layout of the other mode comes next."""

    def dock_of(self, name: str) -> Optional[str]:
        """The dock that shows the dock `name` now; None: none does."""
        return name

    def reveal(self, name: str) -> str:
        """Get the dock `name` shown; the dock to bring to the front."""
        return name


class Pro(Mode):
    key, title = "pro", "Pro"
    tip = "Perspectives and a dock per measurement"
    state_key = "window/docks"  # also the layouts saved before the modes
    perspectives = True
    measure_column = tuple(
        dock_name(MEASURE, procedure)
        for procedure in ("sis.iv_curve", "sis.pv_curve", "monitor.time")
    )


class Lite(Mode):
    """The Pro docks of measurements stay closed: the chosen one's widget is
    borrowed into the Measurement dock, so a run started in one mode goes
    on in the other."""

    key, title = "lite", "Lite"
    tip = "One layout; measurements run from the bar on top"
    state_key = "window/docks_lite"
    run_bar = True
    measure_column = (MEASUREMENT,)

    def __init__(
        self,
        bar: RunBar,
        host: MeasurementHost,
        docks: Mapping[str, QtAds.CDockWidget],
        settings: QSettings,
    ):
        self.bar = bar
        self.host = host
        self.docks = docks  # the window's, MEASUREMENT among them
        self.settings = settings
        self.chosen: Optional[str] = None
        bar.chosen.connect(self.choose)

    def enter(self) -> None:
        for name, dock in self.docks.items():
            if key_of(name, MEASURE) and not dock.isClosed():
                dock.toggleView(False)
        chosen = self.settings.value(CHOSEN_KEY) or DEFAULT_MEASUREMENT
        if dock_name(MEASURE, chosen) not in self.docks:
            chosen = DEFAULT_MEASUREMENT
        self.choose(chosen)

    def leave(self) -> None:
        self.host.release()  # back to the Pro docks
        self.docks[MEASUREMENT].toggleView(False)

    def choose(self, procedure: str) -> None:
        """The measurement the bar runs and the Measurement dock shows; one
        that runs goes on running."""
        pro = self.docks.get(dock_name(MEASURE, procedure))
        if pro is None:
            return
        content = self.host.take(pro.widget())
        self.bar.show_run(procedure, content.box)
        dock = self.docks[MEASUREMENT]
        dock.setWindowTitle(pro.windowTitle())
        dock.setIcon(pro.icon())
        self.chosen = procedure
        self.settings.setValue(CHOSEN_KEY, procedure)

    def dock_of(self, name: str) -> Optional[str]:
        procedure = key_of(name, MEASURE)
        if procedure is None:
            return name
        return MEASUREMENT if procedure == self.chosen else None

    def reveal(self, name: str) -> str:
        procedure = key_of(name, MEASURE)
        if procedure is None:
            return name
        self.choose(procedure)
        return MEASUREMENT
