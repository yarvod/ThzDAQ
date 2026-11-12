"""Operations on the windows of people: what agents ask of a window (asked
of the window itself) and what a window tells or answers."""

import msgspec
from thzdaq_api import ui as api
from thzdaq_api.procedures import current_name

from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.handlers.measurements import build
from thzdaq_core.application.procedures import Procedures
from thzdaq_core.application.windows import Windows


class UiState(Handler[api.UiState, api.WindowState]):
    """The window's state, with every window open (the window knows only
    itself)."""

    operation = api.UiState

    def __init__(self, windows: Windows):
        self.windows = windows

    def handle(self, args, origin):
        state = self.windows.ask(args, origin)
        return msgspec.structs.replace(state, windows=self.windows.open())


class UiOpen(Handler[api.UiOpen, None]):
    operation = api.UiOpen

    def __init__(self, windows: Windows):
        self.windows = windows

    def handle(self, args, origin):
        self.windows.ask(args, origin)


class UiFillMeasurement(Handler[api.UiFillMeasurement, api.FormState]):
    """Values are checked and turned into SI here, as a start's are: the
    window gets them as its form holds them."""

    operation = api.UiFillMeasurement

    def __init__(self, windows: Windows, procedures: Procedures):
        self.windows = windows
        self.procedures = procedures

    def handle(self, args, origin):
        procedure = build(self.procedures, args.procedure, args.parameters, args.typed)
        given = {**args.parameters, **args.typed}
        values = {k: v for k, v in procedure.to_json().items() if k in given}
        filled = msgspec.structs.replace(
            args, procedure=current_name(args.procedure), parameters=values, typed={}
        )
        return self.windows.ask(filled, origin)


class UiHighlight(Handler[api.UiHighlight, None]):
    operation = api.UiHighlight

    def __init__(self, windows: Windows):
        self.windows = windows

    def handle(self, args, origin):
        self.windows.ask(args, origin)


class WindowActive(Handler[api.WindowActive, None]):
    operation = api.WindowActive

    def __init__(self, windows: Windows):
        self.windows = windows

    def handle(self, args, origin):
        self.windows.activated(args.window)


class AnswerUi(Handler[api.AnswerUi, None]):
    operation = api.AnswerUi

    def __init__(self, windows: Windows):
        self.windows = windows

    def handle(self, args, origin):
        self.windows.answer(args.id, args.result, args.failure)
