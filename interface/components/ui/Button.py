from PyQt6 import QtCore, QtGui
from PyQt6.QtWidgets import QPushButton


class Button(QPushButton):
    loading_gif = "./assets/loading.gif"

    def __init__(self, *args, animate: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.animate = animate
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

    @QtCore.pyqtSlot()
    def start(self):
        if hasattr(self, "_movie"):
            self._movie.start()

    @QtCore.pyqtSlot()
    def stop(self):
        if hasattr(self, "_movie"):
            self._movie.stop()
            self.setIcon(QtGui.QIcon())

    def setGif(self, filename: str):
        if not hasattr(self, "_movie"):
            self._movie = QtGui.QMovie(self)
            self._movie.setFileName(filename)
            self._movie.frameChanged.connect(self.on_frameChanged)
            if self._movie.loopCount() != -1:
                self._movie.finished.connect(self.start)
        self.stop()

    @QtCore.pyqtSlot(int)
    def on_frameChanged(self, frameNumber):
        self.setIcon(QtGui.QIcon(self._movie.currentPixmap()))
