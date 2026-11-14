"""The tab of a script's file in Editor: the text in the editor, above it
Save, Check, Run, Ask, pieces to insert and VS Code, under it the problems a
check found and what its last run printed. A file changed outside (VS Code,
an agent, the assistant) shows in the text hunk by hunk, kept or undone, when
nothing here is unsaved; else a banner asks: Reload, Keep mine, or Compare
(the file's hunks taken into the text here or not).

The assistant writes code where the cursor is (Ask, Ctrl+I) and mends the
text when its last run failed (Fix beside its output, with the traceback):
proposals, shown hunk by hunk for the person to take.

Run of one of the bench's own measurements is Start of its dock, with the
values of its form; another script runs in the daemon as thzdaq script start
does. In console runs code in a console of the window, its names left there
to look at: the selection (the line of the cursor without one, Alt+Shift+E),
or the file as %run runs it, saved first. A text a measurement kept is saved
into the library under a name.

It shows a CodeModel and calls its methods; the window's CodeDocks makes,
names and closes these tabs.
"""

import textwrap
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api import console
from thzdaq_api.custom import CustomCheck

from thzdaq_gui import theme
from thzdaq_gui.assistant.hints import IN_FILE
from thzdaq_gui.editor import CodeEditor
from thzdaq_gui.external_editor import ExternalEditor
from thzdaq_gui.models.code import CodeModel
from thzdaq_gui.models.hints import NO_SERVER, HintsModel, Request
from thzdaq_gui.review_bar import KEEP_MINE
from thzdaq_gui.script_output import OpenPlace, ScriptOutput, failure

UNSAVED = " ●"  # after the title of a tab whose text is not saved
SAVE_TO_LIBRARY = "Save to library"
PROBLEMS, OUTPUT = 0, 1  # tabs under the text
RUN_SELECTION = QKeySequence(
    "Alt+Shift+E"
)  # as PyCharm runs a selection in its console
PARAGRAPH = "\u2029"  # how Qt ends the lines of a selection
NO_PROBLEMS = "No problems found"
ASK_TIP = "Code written here by the assistant, asked in words (Ctrl+I)"
FIX_TIP = "The assistant mends the script by the error of its last run"
FIXING = "The assistant mends it…"
# Pieces of a measurement to insert where the cursor is
PIECES = {
    "Sweep loop": (
        "for v in m.sweep(voltage):\n"
        "    bias.voltage_set = v\n"
        "    m.sleep(settle)\n"
        '    m.record("iv", voltage=bias.read().voltage)\n'
        "    m.progress()\n"
    ),
    "Restore at the end": 'm.restore(bias, "voltage_set")\n',
    "Declared plot": 'pv = plot("P-V", table="pv", x="voltage", y="power")\n',
    "Hot/cold step": (
        'for state in ("hot", "cold"):\n'
        '    getattr(load, f"to_{state}")()\n'
        "    m.sleep(load_settle)\n"
    ),
    "Declared value": 'settle = value("Settle", 10, unit="ms")\n',
    "Declared device": 'bias = device("SIS bias", kind="sis_bias")\n',
}


def indented(piece: str, indent: str) -> str:
    """A piece at the indent of the line it goes into: its later lines too."""
    lines = piece.splitlines(keepends=True)
    return lines[0] + "".join(indent + line for line in lines[1:])


class CodeWidget(QWidget):
    title_changed = Signal(str)  # with the mark of unsaved changes
    library_requested = Signal(str)  # a text without a file: save it so
    start_requested = Signal(str)  # a measurement of the library: start it
    console_requested = Signal(str)  # code to run in a console

    def __init__(
        self,
        model: CodeModel,
        run_file: Callable[[Path], None],
        open_place: OpenPlace,
        hints: HintsModel,
        parent=None,
    ):
        """run_file(path): a script of the workspace started in the daemon;
        open_place(file, line): a place of a traceback opened; hints: the
        assistant's code."""
        super().__init__(parent)
        self.model = model
        self.run_file = run_file
        self.hints = hints
        self.fixing: Optional[Request] = None
        self.external = ExternalEditor(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._toolbar())
        layout.addWidget(self._banner())
        self.editor = CodeEditor(model.complete, hints, IN_FILE)
        self.editor.setPlainText(model.saved_text)
        self.editor.document().setModified(False)
        self.editor.textChanged.connect(self.show_title)
        self.editor.review_ended.connect(self.show_title)
        self.editor.saved.connect(self.save)
        self.problems = QListWidget()
        self.problems.itemActivated.connect(self._go_to_problem)
        self.output = ScriptOutput(open_place, "What its last run printed")
        self.output.textChanged.connect(self.show_hints)
        self.below = QTabWidget()
        self.below.addTab(self.problems, "Problems")
        self.below.addTab(self.output, "Output")
        self.below.setCornerWidget(self._fix_corner())
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.editor)
        split.addWidget(self.below)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.then: Optional[Callable[[], None]] = None  # what waits for the save
        model.saved.connect(self._saved)
        model.failed.connect(self._not_saved)
        model.checked.connect(self.show_check)
        model.failed.connect(self.tell)
        model.disk_changed.connect(self.disk_changed)
        model.printed.connect(self.output.add)
        model.output_reset.connect(self.output.show_whole)
        model.output_reset.connect(lambda _: self.below.setCurrentIndex(OUTPUT))
        hints.availability_changed.connect(self.show_hints)
        self.show_title()
        self.show_hints()

    def _toolbar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 4, 4, 0)
        model = self.model
        if model.path is None:
            row.addWidget(
                theme.tool_button(
                    SAVE_TO_LIBRARY, "content-save-outline",
                    "Save it as a measurement of the bench's own", self.to_library,
                )
            )  # fmt: skip
        else:
            row.addWidget(
                theme.tool_button(
                    "Save", "content-save-outline", "Save (Ctrl+S)", self.save
                )
            )
        row.addWidget(
            theme.tool_button(
                "Check", "check-all",
                "Syntax, names, its form and what it names of the bench", self.check,
            )
        )  # fmt: skip
        self.runButton = theme.tool_button(
            "Run", "play", "Start it (its dock's values for a measurement)", self.run
        )
        self.runButton.setEnabled(model.path is not None)
        row.addWidget(self.runButton)
        row.addWidget(self._console_button())
        self.askButton = theme.tool_button(
            "Ask", "creation", ASK_TIP, lambda: self.editor.ask()
        )
        row.addWidget(self.askButton)
        insert = QToolButton()
        insert.setText("Insert")
        insert.setIcon(theme.icon("code-braces"))
        insert.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        insert.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(insert)
        for title, piece in PIECES.items():
            menu.addAction(title, lambda piece=piece: self.insert(piece))
        insert.setMenu(menu)
        row.addWidget(insert)
        row.addStretch()
        if model.path is not None:
            row.addWidget(
                theme.tool_button(
                    "VS Code", "microsoft-visual-studio-code",
                    "Open it in VS Code (a debugger, step by step)", self.open_outside,
                )
            )  # fmt: skip
        return bar

    def _console_button(self) -> QToolButton:
        button = QToolButton()
        button.setText("In console")
        button.setIcon(theme.icon("console"))
        button.setToolTip("Run code of it in a console, its names left there")
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setPopupMode(QToolButton.InstantPopup)
        self.runSelection = QAction("Run selection in console", self)
        self.runSelection.setShortcut(RUN_SELECTION)
        self.runSelection.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.runSelection.triggered.connect(self.run_selection)
        self.addAction(self.runSelection)
        self.runFile = QAction("Run file in console", self)
        self.runFile.setEnabled(self.model.path is not None)
        self.runFile.triggered.connect(self.run_file_in_console)
        menu = QMenu(button)
        menu.addAction(self.runSelection)
        menu.addAction(self.runFile)
        button.setMenu(menu)
        return button

    def _banner(self) -> QFrame:
        self.banner = QFrame()
        self.banner.setStyleSheet(
            f"QFrame {{ background: #4a3a1c; border: 1px solid {theme.ACCENT}; }}"
        )
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(8, 4, 8, 4)
        self.bannerText = QLabel("The file changed outside while it has changes here")
        row.addWidget(self.bannerText, 1)
        reload = QPushButton("Reload")
        reload.clicked.connect(self.reload)
        keep = QPushButton(KEEP_MINE)
        keep.clicked.connect(self.keep_mine)
        compare = QPushButton("Compare")
        compare.setToolTip("The file's changes in your text, each taken or not")
        compare.clicked.connect(self.compare)
        row.addWidget(reload)
        row.addWidget(keep)
        row.addWidget(compare)
        self.banner.hide()
        self.on_disk = ""
        return self.banner

    def _fix_corner(self) -> QWidget:
        corner = QWidget()
        row = QHBoxLayout(corner)
        row.setContentsMargins(0, 0, 4, 0)
        self.fixStatus = QLabel()
        self.fixStatus.setStyleSheet(f"color: {theme.MUTED};")
        self.fixButton = theme.tool_button("Fix", "auto-fix", FIX_TIP, self.fix)
        row.addWidget(self.fixStatus)
        row.addWidget(self.fixButton)
        return corner

    # Its text
    @property
    def text(self) -> str:
        """Its text; while a change is looked at, with what is decided of it."""
        return self.editor.code()

    def unsaved(self) -> bool:
        return self.model.dirty(self.text)

    def title(self) -> str:
        return self.model.title + (UNSAVED if self.unsaved() else "")

    def show_title(self) -> None:
        self.title_changed.emit(self.title())

    def save(self) -> None:
        if self.model.path is None:
            self.to_library()
        else:
            self.model.save(self.text)

    def to_library(self) -> None:
        self.library_requested.emit(self.text)

    def insert(self, piece: str) -> None:
        cursor = self.editor.textCursor()
        line = cursor.block().text()
        indent = line[: len(line) - len(line.lstrip(" "))]
        cursor.insertText(indented(piece, indent))
        self.editor.setFocus()

    def open_outside(self) -> None:
        path = self.model.path
        line = self.editor.textCursor().blockNumber() + 1
        self.external.open(path.parent, path, line)

    def go_to(self, line: int) -> None:
        if line:
            self.editor.go_to(line)

    # Changed outside
    def disk_changed(self, text: str) -> None:
        if not self.unsaved():
            self.editor.show_review(self.model.outside(self.text, text))
            self.show_title()
        else:
            self.on_disk = text
            self.banner.show()

    def reload(self) -> None:
        self.model.take(self.on_disk)
        line = self.editor.textCursor().blockNumber() + 1
        self.editor.set_text(self.on_disk)
        self.editor.go_to(line)
        self.banner.hide()
        self.show_title()

    def keep_mine(self) -> None:
        """The text here stays, not saved: the file has the other one."""
        self.model.take(self.on_disk)
        self.banner.hide()
        self.show_title()

    def compare(self) -> None:
        self.editor.show_review(self.model.compare(self.text, self.on_disk))
        self.banner.hide()
        self.show_title()

    # The assistant's code
    def show_hints(self) -> None:
        """Ask and Fix work with the assistant's server; Fix once its last
        run failed."""
        on = self.hints.available()
        self.askButton.setEnabled(on)
        self.askButton.setToolTip(ASK_TIP if on else NO_SERVER)
        failed = failure(self.output.toPlainText()) is not None
        self.fixButton.setEnabled(on and failed and self.fixing is None)
        self.fixButton.setToolTip(FIX_TIP if on else NO_SERVER)

    def fix(self) -> None:
        error = failure(self.output.toPlainText())
        if error is None or self.fixing is not None:
            return
        code = self.text
        self.fixing = self.hints.fix(IN_FILE, code, error, (), self)
        self.fixing.answered.connect(lambda text: self._fixed(code, text))
        self.fixing.failed.connect(self._fix_failed)
        self.fixStatus.setText(FIXING)
        self.show_hints()

    def _fixed(self, code: str, text: str) -> None:
        self.fixing = None
        self.fixStatus.setText(self.editor.propose(code, text) or "")
        self.show_hints()

    def _fix_failed(self, why: str) -> None:
        self.fixing = None
        self.fixStatus.setText(why)
        self.show_hints()

    # Check and run
    def check(self) -> None:
        self.model.check(self.text)

    def show_check(self, checked: CustomCheck) -> None:
        self.problems.clear()
        for problem in checked.problems:
            where = f"{problem.line}: " if problem.line else ""
            item = QListWidgetItem(f"{where}{problem.text}  ({problem.kind})")
            item.setData(Qt.UserRole, problem.line or 0)
            item.setToolTip(problem.text)
            self.problems.addItem(item)
        if not checked.problems:
            self.problems.addItem(NO_PROBLEMS)
        self.editor.set_problems(
            {p.line: p.text for p in checked.problems if p.line is not None}
        )
        self.below.setTabText(PROBLEMS, f"Problems ({len(checked.problems)})")
        self.below.setCurrentIndex(PROBLEMS)

    def _go_to_problem(self, item: QListWidgetItem) -> None:
        self.go_to(item.data(Qt.UserRole) or 0)

    def run(self) -> None:
        """Saved first: the daemon runs the file, and the measurement keeps
        the text it ran; it starts once the save is done."""
        self.below.setCurrentIndex(OUTPUT)
        self.saved_then(self._start)

    def saved_then(self, then: Callable[[], None]) -> None:
        """then, once the text is its file's (saved first when it is not)."""
        if self.unsaved():
            self.then = then
            self.save()
        else:
            then()

    def _saved(self) -> None:
        self.show_title()
        then, self.then = self.then, None
        if then is not None:
            then()

    # In a console
    def selected_code(self) -> str:
        """The selection, or the line of the cursor; dedented, so a piece of a
        block runs alone."""
        cursor = self.editor.textCursor()
        text = cursor.selectedText() if cursor.hasSelection() else cursor.block().text()
        return textwrap.dedent(text.replace(PARAGRAPH, "\n"))

    def run_selection(self) -> None:
        code = self.selected_code()
        if code.strip():
            self.console_requested.emit(code)

    def run_file_in_console(self) -> None:
        self.saved_then(
            lambda: self.console_requested.emit(console.run_file(self.model.path))
        )

    def _start(self) -> None:
        if self.model.procedure is not None:
            self.start_requested.emit(self.model.procedure)
        else:
            self.run_file(self.model.path)

    def _not_saved(self, _message: str) -> None:
        self.then = None

    def tell(self, message: str) -> None:
        QMessageBox.warning(self, self.model.title, message)

    # Closing
    def may_close(self) -> bool:
        """Unsaved changes are saved, dropped, or keep it open."""
        if not self.unsaved():
            return True
        answer = QMessageBox.question(
            self,
            self.model.title,
            f"{self.model.title} has changes not saved: save them?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if answer == QMessageBox.Save:
            self.save()
        return answer != QMessageBox.Cancel
