"""Content of a heavy dock (a device, a measurement), held in the dock only while open.

Opening a perspective, ADS moves every dock, closed ones too, into new areas,
and Qt restyles the whole widget tree of each moved dock (the application
style sheet): with every device and measurement dock built that took most of
a second. A DockBody detaches its content while the dock is closed, so a
switch costs only the open docks. The content is built on the first open and
keeps working while detached (monitors, running measurements).
"""

from typing import Callable, Optional

from PySide6.QtWidgets import QVBoxLayout, QWidget

from thzdaq_gui.graphs import close_views

Factory = Callable[[], QWidget]


class DockBody(QWidget):
    def __init__(self, factory: Factory, parent=None):
        super().__init__(parent)
        self._factory = factory
        self._content: Optional[QWidget] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    @property
    def built(self) -> bool:
        return self._content is not None

    @property
    def attached(self) -> bool:
        return self._content is not None and self._content.parent() is self

    def content(self) -> QWidget:
        if self._content is None:
            self._content = self._factory()
        return self._content

    def set_open(self, open_: bool) -> None:
        if open_:
            if not self.attached:
                content = self.content()
                self.layout().addWidget(content)
                content.show()
        elif self.attached:
            content = self._content
            content.hide()  # first: a visible widget without a parent is a window
            self.layout().removeWidget(content)
            content.setParent(None)

    def lend(self) -> QWidget:
        """The content, out of this dock to be shown elsewhere (Lite); it
        comes back on the next set_open(True)."""
        self.set_open(False)
        return self.content()

    def replace(self, factory: Factory) -> None:
        """New content (an edited device), shown in place of the old one."""
        attached = self.attached
        self.dispose()
        self._factory = factory
        if attached:
            self.set_open(True)

    def stop(self) -> None:
        if self._content is not None and hasattr(self._content, "stop"):
            self._content.stop()

    def dispose(self) -> None:
        if self._content is None:
            return
        self.stop()
        self.set_open(False)
        close_views(self._content)  # a device dock with a trace plot
        self._content.deleteLater()
        self._content = None

    # The content's attributes and children, as if it were the dock widget
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.content(), name)

    def findChildren(self, *args):
        return self.content().findChildren(*args)
