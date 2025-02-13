from PySide6 import QtCore, QtGui
from PySide6.QtWidgets import QPushButton


class Button(QPushButton):
    loading_gif = "./assets/loading.gif"

    def __init__(
        self, *args, animate: bool = False, icon: QtGui.QIcon = None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.animate = animate
        self._icon = icon
        if icon:
            self.setIcon(icon)
        if self.animate:
            self.setGif(self.loading_gif)

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        if not self.animate:
            return
        if enabled:
            self.stop()
        else:
            self.start()

    @QtCore.Slot()
    def start(self):
        if hasattr(self, "_movie"):
            self._movie.start()

    @QtCore.Slot()
    def stop(self):
        if hasattr(self, "_movie"):
            self._movie.stop()
            if self._icon:
                self.setIcon(QtGui.QIcon(self._icon))
            else:
                self.setIcon(QtGui.QIcon())

    def setGif(self, filename: str):
        if not hasattr(self, "_movie"):
            self._movie = QtGui.QMovie(self)
            self._movie.setFileName(filename)
            self._movie.frameChanged.connect(self.on_frameChanged)
            if self._movie.loopCount() != -1:
                self._movie.finished.connect(self.start)
        self.stop()

    @QtCore.Slot(int)
    def on_frameChanged(self, frameNumber):
        self.setIcon(QtGui.QIcon(self._movie.currentPixmap()))
