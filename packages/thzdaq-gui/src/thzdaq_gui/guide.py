"""What agents ask of this window (thzdaq_api.ui): its state, a place shown,
the form of a measurement filled, a place highlighted.

WindowGuide is the one owner of these requests in a window. It hears those
addressed to this window (ui_requested, by the session's window id), asks
the owners of what the window shows and answers through the daemon
(answer_ui): Places shows a dock, a measurement, a field of its form or a
control of the run bar and gives the widget to point at; the run bar tells
and fills the chosen measurement's form; the docks tell where they are. A
highlight is an OverlayGuide, one at a time. It also tells the daemon when
the person comes to the window: agents that name no window ask this one.
"""

import logging
from typing import Optional

import msgspec
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget
from thzdaq_api import ui, wire
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import UiRequested
from thzdaq_api.operation import Operation

from thzdaq_gui.docking import DockSpace
from thzdaq_gui.navigator import Places
from thzdaq_gui.overlay import OverlayGuide
from thzdaq_gui.runbar import RunBar

logger = logging.getLogger(__name__)


class WindowGuide(QObject):
    def __init__(
        self,
        session,
        places: Places,
        run_bar: RunBar,
        docks: DockSpace,
        window: QWidget,
    ):
        super().__init__(window)
        self.session = session
        self.places = places
        self.run_bar = run_bar
        self.docks = docks
        self.overlay: Optional[OverlayGuide] = None
        self.answers = {
            ui.UiState: self.state,
            ui.UiOpen: self.open,
            ui.UiFillMeasurement: self.fill,
            ui.UiHighlight: self.highlight,
        }
        session.bridge.ui_requested.connect(self.asked)
        window.installEventFilter(self)

    def asked(self, body: UiRequested) -> None:
        if body.window != self.session.window:
            return
        operation = wire.decode_arguments(body.operation, wire.encode(body.arguments))
        try:
            result = self.answers[type(operation)](operation)
        except LabError as e:
            self.tell(ui.AnswerUi(id=body.id, failure=e.failure()))
        else:
            self.tell(ui.AnswerUi(id=body.id, result=msgspec.to_builtins(result)))

    def tell(self, operation: Operation) -> None:
        """To the daemon; one that went (or an answer too late) is only logged."""
        try:
            self.session.call(operation)
        except LabError as e:
            logger.warning(f"{operation.name} not told: {e}")

    def state(self, args: ui.UiState) -> ui.WindowState:
        session = self.session
        simulated = " (simulated)" if session.simulate else ""
        return ui.WindowState(
            session.window,
            f"{session.workspace.name}, profile {session.profile().name}{simulated}",
            tuple(self.docks.described()),
            tuple(self.run_bar.described()),
            self.run_bar.form_state(),
            tuple(sorted(self.run_bar.measures.running())),
        )

    def open(self, args: ui.UiOpen) -> None:
        self.reveal(args.place)

    def reveal(self, name: str) -> QWidget:
        widget = self.places.reveal(name)
        if widget is None:
            raise LabError(
                ErrorCode.NOT_FOUND,
                f"No place {name} in the window",
                "ui_state names its docks, fields and controls",
            )
        return widget

    def fill(self, args: ui.UiFillMeasurement) -> ui.FormState:
        return self.run_bar.fill(args.procedure, args.parameters, args.devices)

    def highlight(self, args: ui.UiHighlight) -> None:
        """One highlight at a time: a new one takes the place of the last."""
        anchor = self.reveal(args.anchor)
        if self.overlay is not None:
            self.overlay.dismiss()
        overlay = self.overlay = OverlayGuide(anchor, args.text)
        overlay.gone.connect(lambda: self.forget(overlay))

    def forget(self, overlay: OverlayGuide) -> None:
        if self.overlay is overlay:
            self.overlay = None

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.WindowActivate:
            self.tell(ui.WindowActive(window=self.session.window))
        return False
