"""Python consoles in the Console dock: a tab per console, each with a kernel
of its own and its own names (Console 1, Console 2...). New console opens
another as the current tab: from the + of the tabs, the empty dock, Ctrl+K.
Closing a tab ends its kernel; closing the window ends them all.

Code from Editor (Run selection in console, Run file in console) runs in the
current console, a new one when none is open. Ctrl+K finds the consoles and
New console (Owner of thzdaq_gui.navigator).
"""

from pathlib import Path
from typing import Dict, List

from thzdaq_api import console

from thzdaq_gui import theme
from thzdaq_gui.dock_names import CONSOLE, dock_name, key_of
from thzdaq_gui.docking import DockSpace
from thzdaq_gui.docks.console import ConsoleWidget
from thzdaq_gui.docks.tabbed import TabbedDock
from thzdaq_gui.models.console import ConsoleModel
from thzdaq_gui.navigator import BEHIND, CLOSED, FRONT, DockEntry
from thzdaq_gui.script_output import OpenPlace

ICON = "console"
HINT = "No console open"
NEW_CONSOLE = "New console"
SECTION = "Consoles"  # of Ctrl+K
NEW = "new"  # console:new, the row of Ctrl+K that opens one
STOP_S = 10.0  # how long the window waits for each kernel as it closes


class ConsoleDocks:
    def __init__(self, session, docks: DockSpace, open_place: OpenPlace):
        """open_place(file, line): a place of a traceback opened. tabs is the
        content of the Console dock (the window adds it among the base docks)."""
        self.session = session
        self.docks = docks
        self.open_place = open_place
        self.made = 0  # consoles opened, to number them
        self.consoles: Dict[str, ConsoleWidget] = {}  # by their number
        self.tabs = TabbedDock(
            HINT, ((NEW_CONSOLE, ICON, self.new),), lambda widget: True
        )
        self.tabs.closed.connect(self.closed)

    def new(self) -> ConsoleWidget:
        """Another console, as the current tab."""
        self.made += 1
        number = str(self.made)
        widget = ConsoleWidget(ConsoleModel(self.session), self.open_place)
        self.consoles[number] = widget
        self.tabs.add(widget, f"Console {number}", "", theme.icon(ICON))
        self.front(widget)
        return widget

    def front(self, widget: ConsoleWidget) -> None:
        """Its tab current, Console unfolded in front, the focus in its input."""
        self.tabs.show_tab(widget)
        self.docks.open(CONSOLE)
        widget.input.setFocus()

    def current(self) -> ConsoleWidget:
        """The console code goes to: the current tab, else a new one."""
        widget = self.tabs.current()
        return widget if widget is not None else self.new()

    def run(self, code: str) -> None:
        """Code from Editor, in the current console (shown)."""
        widget = self.current()
        self.front(widget)
        widget.run(code)

    def run_file(self, path: Path) -> None:
        self.run(console.run_file(path))

    def closed(self, widget: ConsoleWidget) -> None:
        """Its tab closed: its kernel ends."""
        widget.model.stop()
        for number, open_widget in list(self.consoles.items()):
            if open_widget is widget:
                del self.consoles[number]

    def close(self) -> None:
        """Every kernel ended (the window closes): waited for, each in turn."""
        kernels = [widget.model.kernel for widget in self.consoles.values()]
        for widget in self.consoles.values():
            widget.model.stop()
        for kernel in kernels:
            kernel.join(STOP_S)
        self.consoles.clear()

    # Ctrl+K: console:<number>, and console:new
    def __contains__(self, name: str) -> bool:
        key = key_of(name, CONSOLE)
        return key == NEW or key in self.consoles

    def listed(self) -> List[DockEntry]:
        entries = [
            DockEntry(dock_name(CONSOLE, number), self.tabs.title(widget), SECTION,
                      theme.icon(ICON))
            for number, widget in self.consoles.items()
        ]  # fmt: skip
        entries.append(
            DockEntry(dock_name(CONSOLE, NEW), NEW_CONSOLE, SECTION, theme.icon("plus"))
        )
        return entries

    def state(self, name: str) -> str:
        widget = self.consoles.get(key_of(name, CONSOLE))
        if widget is None:
            return CLOSED
        shown = self.docks.state(CONSOLE) == FRONT and self.tabs.current() is widget
        return FRONT if shown else BEHIND

    def show(self, name: str) -> None:
        key = key_of(name, CONSOLE)
        if key == NEW:
            self.new()
        elif key in self.consoles:
            self.front(self.consoles[key])

    def toggle(self, name: str) -> None:
        """A console is only shown (Console stays among the base docks)."""
        self.show(name)
