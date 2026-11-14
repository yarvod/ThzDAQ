"""The tab of a console in Console: what it ran and came of it above, the
input below in the editor of scripts (colours, indents, completions), its
state, Interrupt, Restart and Clear on top.

Keys of the input: Enter runs a complete block, else goes on to a new line;
Shift+Enter is always a new line, Ctrl+Enter always runs; ↑ on the first line
and ↓ on the last browse the inputs of every console; Ctrl+R searches them
(Ctrl+R again: an older one, Enter takes it, Esc goes back); Ctrl+C with
nothing selected interrupts what runs (the Control key on macOS too, where ⌘C
copies); Ctrl+Space or a dot asks the kernel for completions.

The assistant's hints work in the input as in the editor of a file: the
ghost while typing, Ctrl+I (Ask) for code asked in words; Fix mends the last
block that raised, told its traceback and the blocks before it. What it
writes comes into the input as a proposal; the person runs it.

It shows a ConsoleModel and calls its methods; the window's ConsoleDocks
makes, names and closes these tabs.
"""

import sys
from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.assistant.hints import IN_CONSOLE
from thzdaq_gui.console_output import ConsoleOutput
from thzdaq_gui.editor import CodeEditor
from thzdaq_gui.models.console import (
    BUSY,
    ENDED,
    IDLE,
    STARTING,
    ConsoleModel,
    complete_block,
)
from thzdaq_gui.models.hints import NO_SERVER, HintsModel, Request
from thzdaq_gui.script_output import OpenPlace

# The key that interrupts with C: Control, which Qt calls Meta on macOS
INTERRUPT = Qt.MetaModifier if sys.platform == "darwin" else Qt.ControlModifier
CONTROL = Qt.ControlModifier | Qt.MetaModifier  # Ctrl+Enter, Ctrl+R: either
STATES = {
    STARTING: ("Starting…", theme.MUTED),
    IDLE: ("Ready", theme.GOOD),
    BUSY: ("Running…", theme.ACCENT),
    ENDED: ("Ended", theme.BAD),
}
HINT = "Python · Enter runs a complete block, Shift+Enter a new line, ↑ earlier ones"
ASK_TIP = "Code written into the input by the assistant, asked in words (Ctrl+I)"
FIX_TIP = "The assistant mends the last block that raised, into the input"
FIXING = "The assistant mends the block that raised…"


class ConsoleInput(CodeEditor):
    run_requested = Signal(str)
    older_requested = Signal()
    newer_requested = Signal()
    search_requested = Signal()
    interrupt_requested = Signal()
    completions_requested = Signal(str, int)  # the code, the cursor in it

    def __init__(self, hints: HintsModel, parent=None):
        super().__init__(None, hints, IN_CONSOLE, parent)
        self.setPlaceholderText(HINT)

    def request_completions(self, text: str, line: int, column: int) -> None:
        """Asked of the kernel: its answer comes to show_completions."""
        self.completions_requested.emit(text, self.textCursor().position())

    def press(self, event) -> None:
        if self.completer.popup().isVisible():
            super().press(event)
            return
        key, modifiers = event.key(), event.modifiers()
        cursor = self.textCursor()
        if key == Qt.Key_C and modifiers & INTERRUPT and not cursor.hasSelection():
            self.interrupt_requested.emit()
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            if modifiers & Qt.ShiftModifier:
                self.new_line()
            elif modifiers & CONTROL or complete_block(self.toPlainText()):
                self.submit()
            else:
                self.new_line()
        elif key == Qt.Key_R and modifiers & CONTROL:
            self.search_requested.emit()
        elif key == Qt.Key_Up and cursor.blockNumber() == 0:
            self.older_requested.emit()
        elif key == Qt.Key_Down and cursor.blockNumber() == self.blockCount() - 1:
            self.newer_requested.emit()
        else:
            super().press(event)

    def submit(self) -> None:
        code = self.toPlainText().rstrip()
        if code.strip():
            self.clear()
            self.run_requested.emit(code)

    def show_text(self, code: str) -> None:
        """In place of what is typed, the cursor at its end."""
        self.setPlainText(code)
        self.moveCursor(self.textCursor().MoveOperation.End)


class ConsoleWidget(QWidget):
    def __init__(
        self,
        model: ConsoleModel,
        open_place: OpenPlace,
        hints: HintsModel,
        parent=None,
    ):
        """open_place(file, line): a place of a traceback opened (in Editor);
        hints: the assistant's code."""
        super().__init__(parent)
        self.model = model
        self.hints = hints
        self.fixing: Optional[Request] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._toolbar())
        self.output = ConsoleOutput(open_place)
        self.input = ConsoleInput(hints)
        below = QWidget()
        column = QVBoxLayout(below)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(self._search_row())
        column.addWidget(self.input)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.output)
        split.addWidget(below)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        model.state_changed.connect(self.show_state)
        model.entered.connect(self.output.add_input)
        model.printed.connect(
            lambda name, text: self.output.add_text(
                text, theme.BAD if name == "stderr" else None
            )
        )
        model.shown.connect(lambda text: self.output.add_text(text + "\n"))
        model.raised.connect(self.output.add_traceback)
        model.told.connect(self.output.add_note)
        model.completed.connect(
            lambda found, start, _end: self.input.show_completions(found, start)
        )
        model.input_requested.connect(self.ask_input)
        self.input.run_requested.connect(model.run)
        self.input.interrupt_requested.connect(model.interrupt)
        self.input.completions_requested.connect(model.complete)
        self.input.older_requested.connect(self.older)
        self.input.newer_requested.connect(self.newer)
        self.input.search_requested.connect(self.start_search)
        model.failed_changed.connect(self.show_hints)
        hints.availability_changed.connect(self.show_hints)
        self.show_state(model.state)
        self.show_hints()

    def _toolbar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 4, 4, 0)
        self.stateLabel = QLabel()
        row.addWidget(self.stateLabel)
        row.addStretch()
        self.askButton = theme.tool_button(
            "Ask", "creation", ASK_TIP, lambda: self.input.ask()
        )
        row.addWidget(self.askButton)
        self.fixButton = theme.tool_button("Fix", "auto-fix", FIX_TIP, self.fix)
        row.addWidget(self.fixButton)
        self.interruptButton = theme.tool_button(
            "Interrupt", "stop", "Interrupt what runs (Ctrl+C)", self.model.interrupt
        )
        row.addWidget(self.interruptButton)
        row.addWidget(
            theme.tool_button(
                "Restart", "restart",
                "A new kernel: its names go, a measurement it runs ends restored",
                self.model.restart,
            )
        )  # fmt: skip
        row.addWidget(
            theme.tool_button(
                "Clear", "notification-clear-all", "Clear the output",
                self.output_cleared,
            )
        )  # fmt: skip
        return bar

    def _search_row(self) -> QLineEdit:
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search inputs: Ctrl+R an older one, Enter takes it, Esc goes back"
        )
        self.search.addAction(
            theme.icon("history", theme.MUTED), QLineEdit.LeadingPosition
        )
        self.search.textEdited.connect(self.find)
        self.search.installEventFilter(self)
        self.search.hide()
        return self.search

    def output_cleared(self) -> None:
        self.output.clear_output()

    def show_state(self, state: str) -> None:
        text, colour = STATES[state]
        self.stateLabel.setText(text)
        self.stateLabel.setStyleSheet(f"color: {colour};")
        self.interruptButton.setEnabled(state == BUSY)

    def run(self, code: str) -> None:
        """Code run here as if typed (from Editor)."""
        self.model.run(code)

    # The assistant's code
    def show_hints(self) -> None:
        """Ask and Fix work with the assistant's server; Fix once a block
        raised."""
        on = self.hints.available()
        self.askButton.setEnabled(on)
        self.askButton.setToolTip(ASK_TIP if on else NO_SERVER)
        failed = self.model.failed is not None
        self.fixButton.setEnabled(on and failed and self.fixing is None)
        self.fixButton.setToolTip(FIX_TIP if on else NO_SERVER)

    def fix(self) -> None:
        failed = self.model.failed
        if failed is None or self.fixing is not None:
            return
        typed = self.input.code()
        self.fixing = self.hints.fix(
            IN_CONSOLE, failed.code, failed.error, failed.before, self
        )
        self.fixing.answered.connect(lambda text: self._fixed(typed, text))
        self.fixing.failed.connect(self._fix_failed)
        self.output.add_note(FIXING)
        self.show_hints()

    def _fixed(self, typed: str, text: str) -> None:
        self.fixing = None
        why = self.input.propose(typed, text)
        if why is not None:
            self.output.add_note(why)
        self.input.setFocus()
        self.show_hints()

    def _fix_failed(self, why: str) -> None:
        self.fixing = None
        self.output.add_note(why)
        self.show_hints()

    # Inputs of earlier
    def older(self) -> None:
        found = self.model.history.older(self.input.toPlainText())
        if found is not None:
            self.input.show_text(found)

    def newer(self) -> None:
        found = self.model.history.newer()
        if found is not None:
            self.input.show_text(found)

    def start_search(self) -> None:
        self.model.history.start_search(self.input.toPlainText())
        self.search.clear()
        self.search.show()
        self.search.setFocus()

    def find(self, text: str, older: bool = False) -> None:
        found = self.model.history.find(text, older) if text else None
        if found is not None:
            self.input.show_text(found)

    def end_search(self, take: bool) -> None:
        """take: the input found stays; else what was typed comes back."""
        typed = self.model.history.end_search()
        if not take:
            self.input.show_text(typed)
        self.search.hide()
        self.input.setFocus()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search and event.type() == QEvent.KeyPress:
            key, modifiers = event.key(), event.modifiers()
            if key == Qt.Key_R and modifiers & CONTROL:
                self.find(self.search.text(), older=True)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
                self.end_search(take=key != Qt.Key_Escape)
                return True
        return super().eventFilter(watched, event)

    def ask_input(self, prompt: str, password: bool) -> None:
        """input() of the code that runs; cancelled, it is interrupted."""
        echo = QLineEdit.Password if password else QLineEdit.Normal
        text, ok = QInputDialog.getText(self, "Input", prompt or "Input:", echo)
        if ok:
            self.model.answer(text)
        else:
            self.model.interrupt()
