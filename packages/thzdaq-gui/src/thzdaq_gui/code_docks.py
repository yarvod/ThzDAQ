"""Docks of scripts' files: one per file, opened as the current tab (the first
between the columns, as a graph), titled by the file and marked while its
text is not saved; closed with unsaved changes, it asks first.

The bench's own measurements are made here: New measurement (a blank one)
and From an example go into the library (write_custom) and open. The script
a measurement kept opens as its text (titled by the measurement), to be saved
into the library under a name.
"""

from pathlib import Path
from typing import Callable, Dict, Optional

import PySide6QtAds as QtAds
from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget
from thzdaq_api import examples
from thzdaq_api.custom import WriteCustom, valid_name
from thzdaq_api.errors import LabError

from thzdaq_gui import theme
from thzdaq_gui.dock_names import CODE, dock_name
from thzdaq_gui.docking import DockSpace
from thzdaq_gui.docks.code import SAVE_TO_LIBRARY, CodeWidget
from thzdaq_gui.models.code import CodeModel

SECTION = "Measures"
GROUP = "Code"
ICON = "language-python"
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
    ):
        """start(procedure): one of the bench's own started as its dock
        starts it."""
        self.session = session
        self.docks = docks
        self.window = window
        self.start = start
        self.texts = 0  # texts opened without a file, to name their docks
        self.widgets: Dict[str, CodeWidget] = {}  # by dock name

    def open(self, path: Path, line: int = 0) -> None:
        """The dock of a file, as the current tab; at a line (from 1)."""
        name = dock_name(CODE, str(Path(path).resolve()))
        if name not in self.docks:
            try:
                model = CodeModel.of_file(self.session, Path(path).resolve())
            except OSError as e:
                QMessageBox.warning(self.window, Path(path).name, str(e))
                return
            self.add(name, model)
        self.docks.open(name)
        self.widgets[name].go_to(line)

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
        name = dock_name(CODE, f"#{self.texts} {title}")
        self.add(name, CodeModel(self.session, None, text, title))
        self.docks.open(name)

    def add(self, name: str, model: CodeModel) -> None:
        widget = CodeWidget(model, self.run_file, self.open_place)
        self.widgets[name] = widget
        dock = self.docks.add(
            name, model.title, widget, SECTION, theme.icon(ICON),
            QtAds.CenterDockWidgetArea, group=GROUP, hint=str(model.path or ""),
            closing=lambda: self.closing(name),
        )  # fmt: skip
        dock.toggleView(False)  # placed by open()
        widget.title_changed.connect(lambda title: self.docks.retitle(name, title))
        widget.start_requested.connect(self.start)
        widget.library_requested.connect(
            lambda text: self.to_library(model.title, text)
        )

    def closing(self, name: str) -> bool:
        """A dock with changes not saved asks first; one that closes goes."""
        if not self.widgets[name].may_close():
            return False
        self.widgets.pop(name)
        return True

    def unsaved(self) -> bool:
        """Some dock holds changes not saved (the window asks before it goes)."""
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
