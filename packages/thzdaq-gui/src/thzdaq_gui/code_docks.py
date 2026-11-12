"""Scripts' files in the Editor dock: a tab per file (and per text a
measurement kept), opened as the current tab at a line, titled by the file
and marked while its text is not saved; closed with unsaved changes, it asks
first. Opening one unfolds Editor at the bottom and puts it in front. The
tab of a library script, opened or made current, chooses its measurement in
the bar.

The bench's own measurements are made here: New measurement (a blank one)
and From an example go into the library (write_custom) and open. The script
a measurement kept opens as its text (titled by the measurement), to be saved
into the library under a name.
"""

from pathlib import Path
from typing import Callable, Dict, Optional

from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget
from thzdaq_api import examples
from thzdaq_api.custom import WriteCustom, valid_name
from thzdaq_api.errors import LabError

from thzdaq_gui import theme
from thzdaq_gui.dock_names import CODE, EDITOR, dock_name
from thzdaq_gui.docking import DockSpace
from thzdaq_gui.docks.code import SAVE_TO_LIBRARY, CodeWidget
from thzdaq_gui.docks.tabbed import TabbedDock
from thzdaq_gui.folders import SCRIPTS
from thzdaq_gui.models.code import CodeModel

ICON = "language-python"
OPEN_SCRIPT = "Open a script…"
HINT = "No script open"
NEW_TITLE = "New measurement"
BLANK = '''"""{title}

What it measures, in a few words.
"""

from thzdaq import connect, device, plot, value

bias = device("SIS bias", kind="sis_bias")
voltage = value("Bias voltage", "0:7:351", unit="mV")

lab = connect()
with lab.measurement("{name}", devices=[bias], exclusive=[bias]) as m:
    m.restore(bias, "voltage_set")
    for v in m.sweep(voltage):
        bias.voltage_set = v
        m.record("points", voltage=bias.read().voltage)
        m.progress()
'''


class CodeDocks:
    def __init__(
        self,
        session,
        docks: DockSpace,
        window: QWidget,
        start: Callable[[str], None],
        choose: Callable[[str], None],
    ):
        """start(procedure): one of the bench's own started as its dock
        starts it; choose(procedure): one of the bench's own whose script is
        the current tab, for the bar. tabs is the content of the Editor dock
        (the window adds it among the base docks)."""
        self.session = session
        self.docks = docks
        self.window = window
        self.start = start
        self.choose = choose
        self.texts = 0  # texts opened without a file, to tell them apart
        # by key: the path of its file, or #<n> <title> of a text
        self.widgets: Dict[str, CodeWidget] = {}
        self.tabs = TabbedDock(
            HINT,
            (
                (OPEN_SCRIPT, "folder-open-outline", self.open_script),
                (f"{NEW_TITLE}…", "plus", self.new_measurement),
            ),
            self.closing,
        )
        self.tabs.closed.connect(self.forget)
        self.tabs.current_changed.connect(self.current_changed)
        # A script run from a file is shown by its tab (its Processes entry)
        docks.show_inside(CODE, lambda key: self.open_place(Path(key), 0))

    def open(self, path: Path, line: int = 0) -> None:
        """The tab of a file, as the current one; at a line (from 1)."""
        key = str(Path(path).resolve())
        widget = self.widgets.get(key)
        if widget is None:
            try:
                model = CodeModel.of_file(self.session, Path(key))
            except OSError as e:
                QMessageBox.warning(self.window, Path(path).name, str(e))
                return
            widget = self.add(key, model)
        self.show(widget, line)

    def open_custom(self, procedure: str, line: int = 0) -> None:
        """The script of one of the bench's own measurements."""
        found = self.session.custom(procedure)
        if found is None:
            QMessageBox.warning(self.window, procedure, f"{procedure} has no script")
            return
        self.open(Path(found.path), line)

    def open_text(self, title: str, text: str) -> None:
        """A text without a file (the script a measurement kept)."""
        self.texts += 1
        key = f"#{self.texts} {title}"
        self.show(self.add(key, CodeModel(self.session, None, text, title)))

    def open_script(self) -> None:
        """A file chosen in a dialog (from the workspace's scripts first)."""
        path = self.session.folders.open_path(
            self.window, SCRIPTS, OPEN_SCRIPT.rstrip("…"), "Python (*.py)"
        )
        if path is not None:
            self.open(path)

    def add(self, key: str, model: CodeModel) -> CodeWidget:
        widget = CodeWidget(model, self.run_file, self.open_place)
        self.widgets[key] = widget
        self.tabs.add(widget, widget.title(), str(model.path or ""), theme.icon(ICON))
        widget.title_changed.connect(lambda title: self.tabs.retitle(widget, title))
        widget.start_requested.connect(self.start)
        widget.library_requested.connect(
            lambda text: self.to_library(model.title, text)
        )
        return widget

    def show(self, widget: CodeWidget, line: int = 0) -> None:
        """Its tab current, Editor unfolded in front, the cursor at the line."""
        self.tabs.show_tab(widget)
        self.current_changed(widget)  # opened again while current: no signal
        self.docks.open(EDITOR)
        widget.go_to(line)
        widget.editor.setFocus()

    def current_changed(self, widget: Optional[CodeWidget]) -> None:
        """The measurement whose script is the current tab is the bar's."""
        path = widget.model.path if widget is not None else None
        procedure = self.session.custom_of(path) if path is not None else None
        if procedure is not None:
            self.choose(procedure)

    def closing(self, widget: CodeWidget) -> bool:
        """A tab with changes not saved asks first."""
        return widget.may_close()

    def forget(self, widget: CodeWidget) -> None:
        """Its tab closed."""
        for key, open_widget in list(self.widgets.items()):
            if open_widget is widget:
                del self.widgets[key]

    def unsaved(self) -> bool:
        """Some tab holds changes not saved (the window asks before it goes)."""
        return any(widget.unsaved() for widget in self.widgets.values())

    def run_file(self, path: Path) -> None:
        self.session.scripts.run(path, dock_name(CODE, str(path)))

    def open_place(self, file: Path, line: int) -> None:
        if Path(file).exists():
            self.open(Path(file), line)

    # The bench's own measurements, made here
    def new_measurement(self) -> None:
        name = self.ask_name(NEW_TITLE, "measurement")
        if name is not None:
            title = name.replace("_", " ").capitalize()
            self.write(name, BLANK.format(title=title, name=name))

    def from_example(self, example: str) -> None:
        found = examples.example(example)
        name = self.ask_name(found.title, self.free_name(found.name))
        if name is not None:
            self.write(name, found.text)

    def to_library(self, title: str, text: str) -> None:
        name = self.ask_name(SAVE_TO_LIBRARY, Path(title.split()[-1]).stem)
        if name is not None:
            self.write(name, text)

    def free_name(self, name: str) -> str:
        """name, or name_2, name_3...: one the library has not."""
        taken = {m.name for m in self.session.library().measurements}
        number, free = 1, name
        while free in taken:
            number += 1
            free = f"{name}_{number}"
        return free

    def ask_name(self, title: str, suggested: str) -> Optional[str]:
        """A name of the library (custom.<name>), asked; None when cancelled.
        One taken is replaced only when the person says so."""
        name, ok = QInputDialog.getText(
            self.window, title, "Name (custom.<name>):", text=self.free_name(suggested)
        )
        name = name.strip()
        if not ok or not name:
            return None
        if not valid_name(name):
            QMessageBox.warning(
                self.window, title, f"{name!r}: letters, digits and _, from a letter"
            )
            return None
        taken = {m.name for m in self.session.library().measurements}
        if name in taken:
            answer = QMessageBox.question(
                self.window, title, f"custom.{name} exists: replace its script?"
            )
            if answer != QMessageBox.Yes:
                return None
        return name

    def write(self, name: str, text: str) -> None:
        """Into the library, then open."""
        try:
            self.session.call(WriteCustom(script=name, text=text))
        except LabError as e:
            QMessageBox.warning(self.window, name, str(e))
            return
        self.open(Path(self.session.library().folder) / f"{name}.py")
