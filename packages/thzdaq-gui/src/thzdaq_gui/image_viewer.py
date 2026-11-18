"""An image viewed large (ImageViewer) and what a chat opens as the person
clicks it (Opener): an image in the viewer, a file in the system's
application for it, the folder that holds a file.

The viewer zooms with the wheel (around the pointer) and its buttons, fits
the image to its window (and keeps it fitted as the window changes, until it
is zoomed) or shows it 1:1; copies it to the clipboard; and saves its
original bytes, the dialog starting where an image was saved last
(folders.IMAGES). It opens fitted when the image is larger than its window,
else 1:1. An image not decoded yet is decoded apart from the GUI thread."""

import mimetypes
from pathlib import Path
from typing import Optional, Protocol

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.decoding import UNREADABLE, decode, size_of
from thzdaq_gui.folders import IMAGES, Folders

ZOOMS = (0.02, 32.0)  # the least and the most
STEP = 1.25  # of a wheel's notch, of a button
NOTCH = 120  # a wheel's notch, in eighths of a degree
SCREEN_SHARE = 0.8  # of the screen the viewer takes at most as it opens
LEAST = QSize(360, 280)
BAR = 48  # what the bar and the margins take of the viewer's height
TITLE = "Image"
SAVE = "Save the image"
NOT_SAVED = "The image was not saved: {why}"
SHOW_IN_FOLDER = "Show in folder"
GONE = "{path} is not there any more."
UNNAMED = "image"  # a saved image's name when it has no file's name


class Viewable(Protocol):
    """An image as the viewer takes it (chat.Image, an attachment's)."""

    data: bytes
    mime: str
    name: str


def file_name(shown: Viewable) -> str:
    """The name an image is saved under first: its own when it is a file's
    of its type, else UNNAMED with its type's extension."""
    if shown.name and mimetypes.guess_type(shown.name)[0] == shown.mime:
        return shown.name
    return UNNAMED + (mimetypes.guess_extension(shown.mime) or "")


class Canvas(QGraphicsView):
    """The image, dragged to move it; the wheel zooms (wheeled: notches,
    more than 0 in); resized as its window is."""

    wheeled = Signal(float)
    resized = Signal()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()

    def wheelEvent(self, event) -> None:
        notches = event.angleDelta().y() / NOTCH
        if notches:
            self.wheeled.emit(notches)
        event.accept()


class ImageViewer(QDialog):
    def __init__(
        self,
        shown: Viewable,
        folders: Folders,
        parent: Optional[QWidget] = None,
        image: Optional[QImage] = None,
    ):
        """image: the image decoded already, when it is."""
        super().__init__(parent)
        self.shown, self.folders = shown, folders
        self.zoom = 1.0
        self.fitting = False  # fitted: it follows the window's size
        self._image: Optional[QImage] = None
        self.setWindowTitle(shown.name or TITLE)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.scene = QGraphicsScene(self)
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(self.item)
        self.canvas = Canvas(self.scene)
        self.canvas.setDragMode(QGraphicsView.ScrollHandDrag)
        self.canvas.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.canvas.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.canvas.setRenderHint(QPainter.SmoothPixmapTransform)
        self.canvas.setBackgroundBrush(QColor(theme.BASE))
        self.canvas.wheeled.connect(
            lambda notches: self.set_zoom(self.zoom * STEP**notches)
        )
        self.canvas.resized.connect(self._refit)

        self.zoomOut = self._button("magnify-minus-outline", "Smaller", self.zoom_out)
        self.zoomIn = self._button("magnify-plus-outline", "Larger", self.zoom_in)
        self.fitButton = self._button(
            "fit-to-screen-outline", "Fit to the window", self.fit
        )
        self.actualButton = self._button(
            "numeric-1-box-outline", "Actual size (1:1)", self.actual
        )
        self.zoomLabel = QLabel()
        self.zoomLabel.setMinimumWidth(44)
        self.sizeLabel = QLabel()
        self.sizeLabel.setProperty("role", "muted")
        self.copyButton = self._button("content-copy", "Copy the image", self.copy)
        self.saveButton = self._button("content-save-outline", f"{SAVE}…", self.save)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        for widget in (
            self.zoomOut,
            self.zoomLabel,
            self.zoomIn,
            self.fitButton,
            self.actualButton,
        ):
            bar.addWidget(widget)
        bar.addSpacing(8)
        bar.addWidget(self.sizeLabel)
        bar.addStretch()
        bar.addWidget(self.copyButton)
        bar.addWidget(self.saveButton)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addLayout(bar)
        layout.addWidget(self.canvas, 1)
        for keys, done in (
            (QKeySequence.ZoomIn, self.zoom_in),
            (QKeySequence.ZoomOut, self.zoom_out),
            (QKeySequence(Qt.CTRL | Qt.Key_0), self.actual),
            (QKeySequence(Qt.CTRL | Qt.Key_9), self.fit),
            (QKeySequence.Copy, self.copy),
            (QKeySequence.Save, self.save),
        ):
            QShortcut(keys, self, done)

        self._ready(False)
        self.resize(self._opening(size_of(shown.data)))
        if image is not None:
            self._decoded(image)
        else:
            decode(shown.data, self._decoded, self)

    @staticmethod
    def _button(icon: str, tip: str, done) -> QToolButton:
        button = QToolButton()
        button.setIcon(theme.icon(icon))
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.clicked.connect(done)
        return button

    def _opening(self, natural: QSize) -> QSize:
        """The viewer's size as it opens: the image's and its bar, within a
        share of the screen."""
        screen = (self.parentWidget() or self).screen().availableGeometry().size()
        most = screen * SCREEN_SHARE
        wanted = natural + QSize(8, BAR) if natural.isValid() else LEAST
        return wanted.expandedTo(LEAST).boundedTo(most)

    def _ready(self, ready: bool) -> None:
        for widget in (
            self.zoomOut, self.zoomIn, self.fitButton, self.actualButton,
            self.copyButton,
        ):  # fmt: skip
            widget.setEnabled(ready)

    def image(self) -> Optional[QImage]:
        return self._image

    def _decoded(self, image: QImage) -> None:
        if image.isNull():
            self.sizeLabel.setText(UNREADABLE)
            return
        self._image = image
        self.item.setPixmap(QPixmap.fromImage(image))
        self.scene.setSceneRect(self.item.boundingRect())
        self.sizeLabel.setText(f"{image.width()} × {image.height()}")
        self._ready(True)
        if self.isVisible():
            self._first_zoom()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._image is not None and not event.spontaneous():
            self._first_zoom()

    def _first_zoom(self) -> None:
        """Fitted when it is larger than the window, else 1:1."""
        room = self.canvas.viewport().size()
        larger = (
            self._image.width() > room.width() or self._image.height() > room.height()
        )
        if larger:
            self.fit()
        else:
            self.actual()

    def set_zoom(self, zoom: float, fitting: bool = False) -> None:
        least, most = ZOOMS
        self.zoom = min(max(zoom, least), most)
        self.fitting = fitting
        self.canvas.setTransform(QTransform.fromScale(self.zoom, self.zoom))
        self.zoomLabel.setText(f"{self.zoom * 100:.0f}%")

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom * STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom / STEP)

    def actual(self) -> None:
        self.set_zoom(1.0)

    def fit(self) -> None:
        """The whole image in the window."""
        if self._image is None:
            return
        room = self.canvas.viewport().size()
        wide = room.width() / self._image.width()
        tall = room.height() / self._image.height()
        self.set_zoom(min(wide, tall), fitting=True)

    def _refit(self) -> None:
        """Fitted, it stays so as its window changes."""
        if self.fitting:
            self.fit()

    def copy(self) -> None:
        if self._image is not None:
            QGuiApplication.clipboard().setImage(self._image)

    def save(self) -> None:
        """The original bytes, as the assistant showed them."""
        extension = mimetypes.guess_extension(self.shown.mime) or ""
        kind = extension[1:].upper() or TITLE
        path = self.folders.save_path(
            self, IMAGES, SAVE, file_name(self.shown),
            f"{kind} image (*{extension});;Any file (*)",
        )  # fmt: skip
        if path is None:
            return
        try:
            path.write_bytes(self.shown.data)
        except OSError as e:
            QMessageBox.warning(self, SAVE, NOT_SAVED.format(why=e.strerror or e))


class Opener:
    """What a chat opens as the person clicks it; viewers are windows of
    their own, over parent."""

    def __init__(self, folders: Folders, parent: QWidget):
        self.folders, self.parent = folders, parent

    def view(self, shown: Viewable, image: Optional[QImage] = None) -> ImageViewer:
        """An image in the viewer; image: decoded already, when it is."""
        viewer = ImageViewer(shown, self.folders, self.parent, image)
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()
        return viewer

    def open(self, path: str) -> None:
        """A file in the system's application for it."""
        if self._there(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def reveal(self, path: str) -> None:
        """The folder that holds a file."""
        if self._there(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _there(self, path: str) -> bool:
        if Path(path).exists():
            return True
        QMessageBox.warning(self.parent, Path(path).name, GONE.format(path=path))
        return False
