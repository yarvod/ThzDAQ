"""Images decoded once and apart from the GUI thread: decode() hands an
image's bytes to Qt's pool of threads (a QImage may be made there, a QPixmap
may not) and its decoded image, scaled down to a side when asked, back to the
GUI thread while whoever asked lives. size_of() reads an image's size from
its header alone, at once.

One owner (_Decoder) keeps the requests that wait, by a number, so a widget
deleted meanwhile is never called: its request goes with it."""

import itertools
from typing import Callable, Dict, Optional

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QCoreApplication,
    QIODevice,
    QObject,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QImage, QImageReader

Ready = Callable[[QImage], None]  # a null image: the bytes are no image Qt reads
UNREADABLE = "An image that cannot be shown"


def size_of(data: bytes) -> QSize:
    """An image's size as its header tells it, nothing decoded; not valid
    when it tells none."""
    array = QByteArray(data)
    buffer = QBuffer(array)  # the reader reads it: both live until it is done
    buffer.open(QIODevice.ReadOnly)
    size = QImageReader(buffer).size()
    buffer.close()
    return size


def _decoded(data: bytes, side: Optional[int]) -> QImage:
    """In a thread of the pool: the image, at most side pixels long, in the
    format a pixmap is made of without a copy."""
    image = QImage.fromData(data)
    if image.isNull():
        return image
    if side is not None and max(image.width(), image.height()) > side:
        image = image.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    alpha = image.hasAlphaChannel()
    return image.convertToFormat(
        QImage.Format_ARGB32_Premultiplied if alpha else QImage.Format_RGB32
    )


class _Decoder(QObject):
    """The requests that wait, answered in the GUI thread."""

    # A request's number and its image, from a thread of the pool: queued
    _done = Signal(int, QImage)

    def __init__(self):
        super().__init__(QCoreApplication.instance())
        self._waiting: Dict[int, Ready] = {}
        self._numbers = itertools.count()
        self._done.connect(self._answer)

    def decode(
        self, data: bytes, ready: Ready, owner: QObject, side: Optional[int]
    ) -> None:
        number = next(self._numbers)
        self._waiting[number] = ready
        owner.destroyed.connect(lambda: self._waiting.pop(number, None))
        done = self._done
        QThreadPool.globalInstance().start(
            lambda: done.emit(number, _decoded(data, side))
        )

    def _answer(self, number: int, image: QImage) -> None:
        ready = self._waiting.pop(number, None)
        if ready is not None:
            ready(image)


_decoder: Optional[_Decoder] = None


def decode(
    data: bytes, ready: Ready, owner: QObject, side: Optional[int] = None
) -> None:
    """Decode data apart from the GUI thread: ready(image) in the GUI thread
    once it is decoded, unless owner was deleted first; side: scaled down to
    at most so many pixels long. From the GUI thread."""
    global _decoder
    if _decoder is None:
        _decoder = _Decoder()
    _decoder.decode(data, ready, owner, side)
