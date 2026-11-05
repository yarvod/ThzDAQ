"""Scripts dock: the scripts of the window's workspace, run in the daemon.

On the left the script folders (scripts/ and those added to the workspace)
with their scripts: New makes one from a template, a double click opens it
in VS Code, Run starts it in the daemon apart from the window. On the right
the scripts the daemon runs and ran lately, whoever started them (those of
other workspaces marked), and what the chosen one printed, as it prints; a
double click on a line of a traceback opens the script at that line. Stop
cancels its measurements, then ends it if it goes on.

It shows a ScriptsModel and calls its methods; the code is edited in VS Code
for now (an editor of the window's own comes later).
"""

import re
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFontDatabase,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api.errors import LabError
from thzdaq_api.scripts import EXITED, RUNNING, STOPPED

from thzdaq_gui import theme
from thzdaq_gui.external_editor import ExternalEditor
from thzdaq_gui.models.scripts import ScriptRun, ScriptsModel

ROLE = Qt.UserRole  # a script's path in the files, a run's id in the runs
TITLE = "Scripts"
# A line of a traceback that names a place: File "/x/scan.py", line 12, in <module>
PLACE = re.compile(r'^\s*File "(?P<file>.+)", line (?P<line>\d+)')
FAILURE = re.compile(r"^(Traceback \(most recent call last\):|\w+(Error|Exception)\b)")


def traceback_place(line: str) -> Optional[Tuple[Path, int]]:
    """The file and line a line of a traceback names; None for another line."""
    found = PLACE.match(line)
    if found is None:
        return None
    return Path(found["file"]), int(found["line"])


def status_text(run: ScriptRun) -> str:
    info = run.info
    if info.status == RUNNING:
        return RUNNING
    return f"{info.status} ({info.exit_code})"


def status_color(run: ScriptRun) -> str:
    info = run.info
    if info.status == RUNNING:
        return theme.ACCENT
    if info.status == EXITED and info.exit_code == 0:
        return theme.GOOD
    return theme.MUTED if info.status == STOPPED else theme.BAD


class Traceback(QSyntaxHighlighter):
    """Places in a traceback as links, its first and last lines as errors."""

    def __init__(self, document):
        super().__init__(document)
        self.place = QTextCharFormat()
        self.place.setForeground(QColor(theme.ACCENT))
        self.place.setFontUnderline(True)
        self.failure = QTextCharFormat()
        self.failure.setForeground(QColor(theme.BAD))

    def highlightBlock(self, text: str) -> None:
        if PLACE.match(text):
            self.setFormat(0, len(text), self.place)
        elif FAILURE.match(text):
            self.setFormat(0, len(text), self.failure)


class Output(QPlainTextEdit):
    """What a script printed; a double click on a place of a traceback opens
    it (open_place(file, line))."""

    def __init__(self, open_place, parent=None):
        super().__init__(parent)
        self.open_place = open_place
        self.setReadOnly(True)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setPlaceholderText("What the chosen script prints")
        self.highlighter = Traceback(self.document())

    def add(self, text: str) -> None:
        """More of the output, at its end (followed when it was shown)."""
        bar = self.verticalScrollBar()
        following = bar.value() == bar.maximum()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        if following:
            bar.setValue(bar.maximum())

    def show_whole(self, text: str) -> None:
        self.setPlainText(text)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def mouseDoubleClickEvent(self, event) -> None:
        line = self.cursorForPosition(event.position().toPoint()).block().text()
        place = traceback_place(line)
        if place is None:
            super().mouseDoubleClickEvent(event)
        else:
            self.open_place(*place)


class ScriptsWidget(QWidget):
    def __init__(self, model: ScriptsModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.editor = ExternalEditor(self)
        self.shown: Optional[int] = None  # the run whose output is shown
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btnNew = self._button(
            "file-plus-outline", "New", "A new script from a template"
        )
        self.btnNew.setPopupMode(QToolButton.InstantPopup)
        self.newMenu = QMenu(self.btnNew)
        for template in model.templates():
            action = self.newMenu.addAction(template.title)
            action.setToolTip(template.about)
            action.triggered.connect(lambda _=False, t=template.name: self.new(t))
        self.newMenu.setToolTipsVisible(True)
        self.btnNew.setMenu(self.newMenu)
        self.btnRun = self._button("play", "Run", "Run the chosen script in the daemon")
        self.btnRun.clicked.connect(self.run_file)
        self.btnStop = self._button(
            "stop", "Stop", "Cancel its measurements, then end it if it goes on"
        )
        self.btnStop.clicked.connect(self.stop_run)
        self.btnCode = self._button(
            "microsoft-visual-studio-code",
            "VS Code",
            "Open the chosen script in VS Code",
        )
        self.btnCode.clicked.connect(self.open_chosen)
        self.btnFolders = self._button(
            "folder-multiple-outline", "Folders", "Folders of scripts"
        )
        self.btnFolders.setPopupMode(QToolButton.InstantPopup)
        folders = QMenu(self.btnFolders)
        self.addFolder = folders.addAction(
            theme.icon("folder-plus-outline"), "Add folder…", self.add_folder
        )
        self.removeFolder = folders.addAction(
            theme.icon("folder-remove-outline"), "Remove folder", self.remove_folder
        )
        folders.addAction(
            theme.icon("folder-outline"), "Show the folder", self.show_folder
        )
        folders.aboutToShow.connect(self.offer_folders)
        self.btnFolders.setMenu(folders)
        for button in (self.btnNew, self.btnRun, self.btnStop, self.btnCode):
            bar.addWidget(button)
        bar.addStretch()
        bar.addWidget(self.btnFolders)
        layout.addLayout(bar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.ACCENT}")
        self.status.hide()
        layout.addWidget(self.status)

        self.files = QTreeWidget()
        self.files.setHeaderHidden(True)
        self.files.itemSelectionChanged.connect(self.file_chosen)
        self.files.itemDoubleClicked.connect(lambda *_: self.open_chosen())
        self.runs = QTreeWidget()
        self.runs.setHeaderLabels(["Script", "Status", "Started", "By"])
        self.runs.setRootIsDecorated(False)
        self.runs.itemSelectionChanged.connect(self.show_chosen_run)
        self.output = Output(self.open_place)
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.runs)
        right.addWidget(self.output)
        right.setStretchFactor(1, 1)
        right.setSizes([110, 290])  # the output matters more than the list
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.files)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 640])
        layout.addWidget(split, 1)

        model.files_changed.connect(self.show_files)
        model.runs_changed.connect(self.show_runs)
        model.printed.connect(self.printed)
        model.output_reset.connect(self.output_reset)
        model.chosen.connect(self.choose_file)
        model.started_here.connect(self.choose_run)
        model.failed.connect(self.tell)
        self.show_files()
        self.show_runs()

    def _button(self, icon_name: str, text: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(theme.icon(icon_name))
        button.setText(text)
        button.setToolTip(tip)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        return button

    def tell(self, message: str) -> None:
        self.status.setText(message)
        self.status.show()

    # Files
    def show_files(self) -> None:
        chosen = self.chosen_file()
        workspace = self.model.session.workspace.folder
        self.files.blockSignals(True)
        self.files.clear()
        for folder, scripts in self.model.files().items():
            shown = (
                folder.relative_to(workspace)
                if folder.is_relative_to(workspace)
                else folder
            )
            top = QTreeWidgetItem([f"{shown.as_posix()}/"])
            top.setIcon(0, theme.icon("folder-outline"))
            top.setData(0, ROLE, str(folder))
            top.setToolTip(0, str(folder))
            for path in scripts:
                item = QTreeWidgetItem([path.relative_to(folder).as_posix()])
                item.setIcon(0, theme.icon("language-python"))
                item.setData(0, ROLE, str(path))
                item.setToolTip(0, str(path))
                top.addChild(item)
            self.files.addTopLevelItem(top)
            top.setExpanded(True)
        self.files.blockSignals(False)
        if chosen is not None:
            self.choose_file(chosen, follow=False)
        self.show_buttons()

    def file_items(self):
        for index in range(self.files.topLevelItemCount()):
            top = self.files.topLevelItem(index)
            for child in range(top.childCount()):
                yield top.child(child)

    def chosen_file(self) -> Optional[Path]:
        items = self.files.selectedItems()
        if not items or items[0].parent() is None:
            return None
        return Path(items[0].data(0, ROLE))

    def chosen_folder(self) -> Optional[Path]:
        """The folder chosen, or the folder of the script chosen."""
        items = self.files.selectedItems()
        if not items:
            return None
        top = items[0].parent() or items[0]
        return Path(top.data(0, ROLE))

    def choose_file(self, path: Path, follow: bool = True) -> None:
        """Show it chosen; follow: its last run too."""
        for item in self.file_items():
            if Path(item.data(0, ROLE)) == Path(path):
                if not follow:
                    self.files.blockSignals(True)
                self.files.setCurrentItem(item)
                self.files.blockSignals(False)
                return

    def file_chosen(self) -> None:
        path = self.chosen_file()
        last = self.model.last_run_of(path) if path is not None else None
        if last is not None:
            self.choose_run(last.id)
        self.show_buttons()

    def new(self, template: str) -> None:
        self.status.hide()
        try:
            self.model.new_script(template)
        except OSError as e:
            QMessageBox.warning(self, TITLE, str(e))

    def open_chosen(self) -> None:
        path = self.chosen_file()
        if path is not None:
            self.open_place(path, None)

    def open_place(self, path: Path, line: Optional[int]) -> None:
        """In VS Code: in the workspace when it is there, else in its folder."""
        workspace = self.model.session.workspace.folder
        folder = workspace if path.is_relative_to(workspace) else path.parent
        self.editor.open(folder, path, line)

    def offer_folders(self) -> None:
        keeps = self.model.keeps_folders()
        self.addFolder.setEnabled(keeps)
        self.addFolder.setToolTip(
            "" if keeps else "Only a workspace keeps them: File → New workspace"
        )
        folder = self.chosen_folder()
        first = self.model.folders()[0]
        self.removeFolder.setEnabled(keeps and folder is not None and folder != first)

    def add_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "A folder of scripts", str(self.model.session.workspace.folder)
        )
        if not chosen:
            return
        try:
            self.model.add_folder(Path(chosen))
        except LabError as e:
            QMessageBox.warning(self, TITLE, str(e))

    def remove_folder(self) -> None:
        folder = self.chosen_folder()
        if folder is None:
            return
        try:
            self.model.remove_folder(folder)
        except LabError as e:
            QMessageBox.warning(self, TITLE, str(e))

    def show_folder(self) -> None:
        folder = self.chosen_folder() or self.model.folders()[0]
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # Runs
    def show_runs(self) -> None:
        chosen = self.chosen_run()
        self.runs.blockSignals(True)
        self.runs.clear()
        for run in self.model.newest_first():
            info = run.info
            name = f"{info.id} {info.name}"
            if not self.model.here(run):
                name += f" · from {Path(info.workspace).name}"
            item = QTreeWidgetItem(
                [name, status_text(run), info.started[11:19], info.by]
            )
            item.setData(0, ROLE, info.id)
            item.setToolTip(0, f"{info.path}\nin {info.workspace}\nlog {info.log}")
            item.setForeground(1, QColor(status_color(run)))
            if not self.model.here(run):
                item.setForeground(0, QColor(theme.MUTED))
            self.runs.addTopLevelItem(item)
        for column in range(self.runs.columnCount()):
            self.runs.resizeColumnToContents(column)
        self.runs.blockSignals(False)
        if chosen is not None:
            self.choose_run(chosen)
        self.show_buttons()

    def chosen_run(self) -> Optional[int]:
        items = self.runs.selectedItems()
        return items[0].data(0, ROLE) if items else None

    def choose_run(self, id: int) -> None:
        for index in range(self.runs.topLevelItemCount()):
            item = self.runs.topLevelItem(index)
            if item.data(0, ROLE) == id:
                self.runs.setCurrentItem(item)
                return

    def show_chosen_run(self) -> None:
        id = self.chosen_run()
        if id != self.shown:
            self.shown = id
            self.output.show_whole("" if id is None else self.model.output(id))
        self.show_buttons()

    def printed(self, id: int, text: str) -> None:
        if id == self.shown:
            self.output.add(text)

    def output_reset(self, id: int) -> None:
        if id == self.shown:
            self.output.show_whole(self.model.output(id))

    def run_file(self) -> None:
        path = self.chosen_file()
        if path is not None:
            self.status.hide()
            self.model.run(path)

    def stop_run(self) -> None:
        id = self.chosen_run()
        if id is not None:
            self.model.stop(id)

    def show_buttons(self) -> None:
        chosen = self.chosen_file() is not None
        self.btnRun.setEnabled(chosen)
        self.btnCode.setEnabled(chosen)
        run = self.model.runs.get(self.chosen_run())
        self.btnStop.setEnabled(run is not None and run.running)
