"""The dock of a script's file: the text in the editor, above it Save, Check,
Run, pieces to insert and VS Code, under it the problems a check found and
what its last run printed. A file changed outside (VS Code, an agent) is
taken at once when nothing here is unsaved, else a banner asks.

Run of one of the bench's own measurements is Start of its dock, with the
values of its form; another script runs in the daemon as thzdaq script start
does. A text a measurement kept is saved into the library under a name.

It shows a CodeModel and calls its methods; the window's CodeDocks makes,
names and closes these docks.
"""

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
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
from thzdaq_api.custom import CustomCheck

from thzdaq_gui import theme
from thzdaq_gui.editor import CodeEditor
from thzdaq_gui.external_editor import ExternalEditor
from thzdaq_gui.models.code import CodeModel
from thzdaq_gui.script_output import OpenPlace, ScriptOutput

UNSAVED = " •"  # after the title of a dock whose text is not saved
SAVE_TO_LIBRARY = "Save to library"
PROBLEMS, OUTPUT = 0, 1  # tabs under the text
NO_PROBLEMS = "No problems found"
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

    def __init__(
        self,
        model: CodeModel,
        run_file: Callable[[Path], None],
        open_place: OpenPlace,
        parent=None,
    ):
        """run_file(path): a script of the workspace started in the daemon;
        open_place(file, line): a place of a traceback opened."""
        super().__init__(parent)
        self.model = model
        self.run_file = run_file
        self.external = ExternalEditor(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._toolbar())
        layout.addWidget(self._banner())
        self.editor = CodeEditor(model.complete)
        self.editor.setPlainText(model.saved_text)
        self.editor.document().setModified(False)
        self.editor.textChanged.connect(self.show_title)
        self.editor.saved.connect(self.save)
        self.problems = QListWidget()
        self.problems.itemActivated.connect(self._go_to_problem)
        self.output = ScriptOutput(open_place, "What its last run printed")
        self.below = QTabWidget()
        self.below.addTab(self.problems, "Problems")
        self.below.addTab(self.output, "Output")
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.editor)
        split.addWidget(self.below)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.starting = False  # a run waits for its save
        model.saved.connect(self._saved)
        model.failed.connect(self._not_saved)
        model.checked.connect(self.show_check)
        model.failed.connect(self.tell)
        model.disk_changed.connect(self.disk_changed)
        model.printed.connect(self.output.add)
        model.output_reset.connect(self.output.show_whole)
        model.output_reset.connect(lambda _: self.below.setCurrentIndex(OUTPUT))
        self.show_title()

    def _button(self, text: str, icon: str, tip: str, slot) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setIcon(theme.icon(icon))
        button.setToolTip(tip)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.clicked.connect(slot)
        return button

    def _toolbar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 4, 4, 0)
        model = self.model
        if model.path is None:
            row.addWidget(
                self._button(
                    SAVE_TO_LIBRARY, "content-save-outline",
                    "Save it as a measurement of the bench's own", self.to_library,
                )
            )  # fmt: skip
        else:
            row.addWidget(
                self._button("Save", "content-save-outline", "Save (Ctrl+S)", self.save)
            )
        row.addWidget(
            self._button(
                "Check", "check-all",
                "Syntax, names, its form and what it names of the bench", self.check,
            )
        )  # fmt: skip
        self.runButton = self._button(
            "Run", "play", "Start it (its dock's values for a measurement)", self.run
        )
        self.runButton.setEnabled(model.path is not None)
        row.addWidget(self.runButton)
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
                self._button(
                    "VS Code", "microsoft-visual-studio-code",
                    "Open it in VS Code (a debugger, step by step)", self.open_outside,
                )
            )  # fmt: skip
        return bar

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
        keep = QPushButton("Keep mine")
        keep.clicked.connect(self.banner.hide)
        row.addWidget(reload)
        row.addWidget(keep)
        self.banner.hide()
        self.on_disk = ""
        return self.banner

    # Its text
    @property
    def text(self) -> str:
        return self.editor.toPlainText()

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
            self._take(text)
        else:
            self.on_disk = text
            self.banner.show()

    def reload(self) -> None:
        self._take(self.on_disk)
        self.banner.hide()

    def _take(self, text: str) -> None:
        self.model.take(text)
        cursor = self.editor.textCursor()
        line = cursor.blockNumber() + 1
        self.editor.setPlainText(text)
        self.editor.go_to(line)
        self.show_title()

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
        if self.unsaved():
            self.starting = True
            self.save()
        else:
            self._start()

    def _saved(self) -> None:
        self.show_title()
        if self.starting:
            self.starting = False
            self._start()

    def _start(self) -> None:
        if self.model.procedure is not None:
            self.start_requested.emit(self.model.procedure)
        else:
            self.run_file(self.model.path)

    def _not_saved(self, _message: str) -> None:
        self.starting = False

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
