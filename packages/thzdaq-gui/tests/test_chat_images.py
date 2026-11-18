"""Images in the assistant's chat (offscreen): made by the built-in mode's
image model on a model's server on localhost (model_server), shown as wide as
the chat and never wider than their pixels, viewed large (zoom, fit, copy,
save), kept in history; what the person attaches opens too."""

import base64
import json
import threading
from pathlib import Path
from typing import List

import pytest
from model_server import calls, png, says
from shots import shot
from thzdaq_gui.assistant.attachments import Attachment
from thzdaq_gui.assistant.chat import Image, Outcome, Said
from thzdaq_gui.assistant.conversation import STOPPED
from thzdaq_gui.assistant.history import CHAT, Recorder, Shelf
from thzdaq_gui.assistant.images import GENERATE, SHOWN, Header, header
from thzdaq_gui.assistant.provider import Provider
from thzdaq_gui.folders import IMAGES, Folders
from thzdaq_gui.models.assistant import (
    AssistantModel,
    CodexSettingsModel,
    InstructionsModel,
    Kind,
    ProvidersModel,
    State,
    built_in_chat,
)
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QScrollArea, QVBoxLayout, QWidget

DRAW = calls((GENERATE, {"prompt": "a red square", "size": "1024x1024"}))


@pytest.fixture(autouse=True)
def no_servers(app):
    yield
    providers = ProvidersModel()
    for provider in providers.all():
        providers.remove(provider.name)


def assistant_of(session, model, image_model):
    providers = ProvidersModel()
    providers.save(Provider("local", model.url, "qwen", image_model=image_model), "k")
    instructions = InstructionsModel()
    chat = built_in_chat(session, providers, instructions)
    return AssistantModel(
        session, providers, instructions, CodexSettingsModel(), [chat]
    )


@pytest.fixture
def assistant(session, model):
    assistant = assistant_of(session, model, "painter")
    yield assistant
    assistant.close()


def kinds(assistant) -> List[Kind]:
    return [item.kind for item in assistant.items if item.kind is not Kind.STATS]


def offered(asked) -> List[str]:
    return [tool["function"]["name"] for tool in asked["tools"]]


def test_an_images_header_tells_its_type_and_size():
    assert header(png(3, 2)) == Header("image/png", 3, 2)
    gif = b"GIF89a" + (5).to_bytes(2, "little") + (7).to_bytes(2, "little") + b"\0" * 8
    assert header(gif) == Header("image/gif", 5, 7)
    jpeg = (
        b"\xff\xd8" + b"\xff\xe0\x00\x04ab"  # a segment before the frame
        + b"\xff\xc0\x00\x11\x08" + (40).to_bytes(2, "big") + (60).to_bytes(2, "big")
    )  # fmt: skip
    assert header(jpeg) == Header("image/jpeg", 60, 40)
    lossless = b"RIFF\0\0\0\0WEBPVP8L\0\0\0\0\x2f" + (
        (9 - 1) | ((4 - 1) << 14)
    ).to_bytes(4, "little")
    assert header(lossless) == Header("image/webp", 9, 4)
    assert header(b"not an image") is None
    assert header(png(3, 2)[:20]) is None  # cut short


def test_the_image_tool_is_offered_only_with_an_image_model(session, model, wait):
    plain = assistant_of(session, model, None)
    plain.send("hello")
    wait(lambda: not plain.busy())
    plain.close()
    assert GENERATE not in offered(model.asked[0])
    drawing = assistant_of(session, model, "painter")
    drawing.send("hello")
    wait(lambda: not drawing.busy())
    drawing.close()
    assert GENERATE in offered(model.asked[1])


def test_a_made_image_is_shown_and_the_model_reads_only_that(assistant, model, wait):
    model.replies = [DRAW, says("Here it is.")]
    assistant.send("draw a red square")
    wait(lambda: not assistant.busy())
    assert kinds(assistant) == [Kind.PERSON, Kind.CALL, Kind.IMAGE, Kind.ANSWER]
    call, shown = assistant.items[1:3]
    told = SHOWN.format(width=3, height=2)
    assert call.state is State.DONE and call.text == told
    assert shown.image == Image(model.drawing, "image/png", "a red square")
    (drawn,) = model.drawn
    assert drawn == {
        "model": "painter", "prompt": "a red square", "n": 1, "size": "1024x1024",
    }  # fmt: skip
    assert model.keys[-2] == "Bearer k"  # the server's key, as for the chat
    answered = model.asked[1]["messages"][-1]
    assert answered["role"] == "tool" and answered["content"] == told
    encoded = base64.b64encode(model.drawing).decode()
    assert encoded not in json.dumps(model.asked[1])  # never the bytes


def test_an_image_given_at_an_address_is_fetched(assistant, model, wait):
    model.by_address = True
    model.replies = [DRAW, says("Done.")]
    assistant.send("draw")
    wait(lambda: not assistant.busy())
    shown = next(item for item in assistant.items if item.kind is Kind.IMAGE)
    assert shown.image.data == model.drawing


def test_a_refused_image_goes_back_to_the_model_and_shows_why(assistant, model, wait):
    model.images_status = 404
    model.replies = [DRAW, says("The server makes no images.")]
    assistant.send("draw")
    wait(lambda: not assistant.busy())
    assert kinds(assistant) == [Kind.PERSON, Kind.CALL, Kind.ANSWER]
    call = assistant.items[1]
    assert call.state is State.REFUSED
    assert call.text == "The image was not made: the server refused (404): nope"
    assert model.asked[1]["messages"][-1]["content"] == call.text


def test_stop_while_it_draws_drops_the_image(assistant, model, wait):
    model.draws.clear()
    model.replies = [DRAW]
    assistant.send("draw")
    wait(lambda: model.drawn)
    assert assistant.phase == f"Running {GENERATE}"
    assistant.stop()
    model.draws.set()  # the server answers after all: dropped
    for turn in [t for t in threading.enumerate() if t.name == "assistant"]:
        turn.join(5)
    wait(lambda: True)
    assert kinds(assistant) == [Kind.PERSON, Kind.CALL, Kind.NOTE]
    assert assistant.items[1].state is State.STOPPED
    messages = assistant.mode.chat.conversation.messages
    assert messages[-1]["content"] == STOPPED and len(model.asked) == 1


def test_an_image_answer_is_kept_and_comes_back_with_the_chat(assistant, model, wait):
    model.replies = [DRAW, says("Here it is.")]
    assistant.send("draw a red square")
    wait(lambda: not assistant.busy())
    shown = [item.kind for item in assistant.items]
    kept = assistant.current_chat()
    assistant.new_chat()
    assistant.find_chats()
    wait(lambda: assistant.chats())
    assistant.open_chat(kept)
    wait(lambda: assistant.items)
    assert [item.kind for item in assistant.items] == shown
    image = next(item for item in assistant.items if item.kind is Kind.IMAGE).image
    assert image == Image(model.drawing, "image/png", "a red square")


class Told:
    """What a kept chat tells as it opens (chat.Replay), images among it."""

    def __init__(self):
        self.images: List[Image] = []
        self.done = threading.Event()

    def __getattr__(self, name):
        return lambda *told, **named: None

    def image(self, image):
        self.images.append(image)

    def opened(self, why=""):
        self.done.set()


def test_a_shown_image_is_kept_once_as_a_file_beside_the_chat(tmp_path):
    shelf = Shelf(tmp_path / "chats")
    said = Said("draw")
    chat = shelf.new(tmp_path / "bench", said)
    image = Image(png(5, 5), "image/png", "a square")
    turn = Recorder(shelf, chat, said, (), Told(), lambda: [])
    turn.image(image)
    turn.image(image)  # shown twice: one file
    turn.ended(Outcome.ANSWERED, "")
    told = Told()
    shelf.open(chat, lambda messages: None, told)
    assert told.done.wait(5)
    assert told.images == [image, image]
    folder = shelf.folder(chat)
    assert "base64" not in (folder / CHAT).read_text(encoding="utf-8")
    assert [path.read_bytes() for path in folder.glob("*.png")] == [image.data]


def picture(data: bytes, name: str = "", wait=None):
    from thzdaq_gui.chat_widgets import Picture

    shown = Picture(data, name)
    if wait is not None:
        wait(lambda: shown.image() is not None)
    return shown


def test_a_picture_fits_the_width_keeps_its_ratio_and_never_grows(app, wait):
    shown = picture(png(200, 100), "a plot", wait)
    left, top, right, bottom = shown.MARGINS
    line = shown.fontMetrics().lineSpacing() + shown.GAP
    assert shown.shown(left + 100 + right) == QSize(100, 50)
    assert shown.heightForWidth(left + 100 + right) == top + 50 + line + bottom
    assert shown.shown(1000) == QSize(200, 100)  # never wider than its pixels
    assert shown.minimumSizeHint().width() <= 60  # never widens the chat
    nameless = picture(png(200, 100))
    assert nameless.heightForWidth(1000) == top + 100 + bottom


def test_a_picture_is_scaled_once_per_width(app, wait):
    shown = picture(png(400, 200), wait=wait)
    first = shown.scaled(QSize(100, 50))
    assert first.deviceIndependentSize().toSize() == QSize(100, 50)
    assert shown.scaled(QSize(100, 50)) is first  # repainted: not scaled again
    assert shown.scaled(QSize(200, 100)) is not first


def test_a_picture_in_the_chat_takes_the_height_its_width_gives(app, wait):
    column = QVBoxLayout()
    holder = QWidget()
    holder.setLayout(column)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(holder)
    shown = picture(png(800, 400), "wide", wait)
    column.addWidget(shown)
    column.addStretch()
    area.resize(320, 600)
    area.show()
    wait(lambda: shown.width() > 0)
    assert shown.height() == shown.heightForWidth(shown.width())
    assert shown.shown(shown.width()).width() <= shown.width()
    assert holder.width() <= area.viewport().width()
    area.close()


def test_what_is_not_an_image_says_so(app):
    shown = picture(b"not an image", "broken")
    assert not shown.readable() and shown.heightForWidth(300) > 0


@pytest.fixture
def folders(tmp_path):
    return Folders({IMAGES: lambda: tmp_path})


@pytest.fixture
def opened(monkeypatch):
    """The URLs the system was asked to open."""
    found = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", staticmethod(lambda url: found.append(url) or True)
    )
    return found


def test_the_viewer_zooms_fits_copies_and_saves(
    app, folders, tmp_path, monkeypatch, wait
):
    from thzdaq_gui.image_viewer import STEP, ImageViewer

    shown = Image(png(400, 300), "image/png", "a red square")
    viewer = ImageViewer(shown, folders)
    viewer.resize(300, 300)
    viewer.show()
    wait(lambda: viewer.image() is not None)
    room = viewer.canvas.viewport().size()
    fitted = min(room.width() / 400, room.height() / 300)
    assert viewer.fitting and viewer.zoom == pytest.approx(fitted)  # larger: fitted
    viewer.actual()
    assert viewer.zoom == 1.0 and not viewer.fitting
    assert viewer.canvas.transform().m11() == 1.0
    viewer.zoom_in()
    assert viewer.zoom == pytest.approx(STEP) and viewer.zoomLabel.text() == "125%"
    viewer.canvas.wheeled.emit(-2.0)  # two notches out
    assert viewer.zoom == pytest.approx(STEP / STEP**2)
    viewer.fit()
    viewer.resize(500, 500)
    room = viewer.canvas.viewport().size()
    assert viewer.zoom == pytest.approx(min(room.width() / 400, room.height() / 300))
    viewer.copy()
    assert QGuiApplication.clipboard().image().size() == QSize(400, 300)
    target = tmp_path / "saved" / "square.png"
    target.parent.mkdir()
    start = folders.folder(IMAGES) / "image.png"
    asked = []

    def chosen(parent, title, start, filters):
        asked.append(start)
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", chosen)
    viewer.save()
    assert target.read_bytes() == shown.data  # the original bytes
    assert asked == [str(start)]
    assert folders.folder(IMAGES).resolve() == target.parent.resolve()  # the next
    shot(viewer, "image_viewer")
    viewer.close()


def test_a_small_image_opens_at_its_own_size(app, folders, wait):
    from thzdaq_gui.image_viewer import ImageViewer

    viewer = ImageViewer(Image(png(20, 10), "image/png"), folders)
    viewer.show()
    wait(lambda: viewer.image() is not None)
    assert viewer.zoom == 1.0 and not viewer.fitting
    viewer.close()


def test_chips_open_an_image_in_the_viewer_and_a_file_in_its_application(
    app, folders, opened, tmp_path, wait
):
    from thzdaq_gui.docks.assistant import OPEN, VIEW, chip
    from thzdaq_gui.image_viewer import SHOW_IN_FOLDER, ImageViewer, Opener

    parent = QWidget()
    opener = Opener(folders, parent)
    picture_file = tmp_path / "plot.png"
    picture_file.write_bytes(png(30, 20))
    pasted = chip(Attachment.image(png(30, 20)), opener)
    assert pasted.offered() == [VIEW]  # pasted: no file to show
    QTest.mouseClick(pasted, Qt.LeftButton, pos=QPoint(4, 4))
    (viewer,) = parent.findChildren(ImageViewer)
    wait(lambda: viewer.image() is not None)
    assert viewer.image().size() == QSize(30, 20)
    viewer.close()
    attached = chip(Attachment.of_file(picture_file), opener, removable=False)
    assert attached.offered() == [VIEW, SHOW_IN_FOLDER]
    notes = tmp_path / "notes.txt"
    notes.write_text("T_rx = 50 K")
    filed = chip(Attachment.of_file(notes), opener, removable=False)
    assert filed.offered() == [OPEN, SHOW_IN_FOLDER]
    QTest.mouseClick(filed, Qt.LeftButton, pos=QPoint(4, 4))
    assert [Path(url.toLocalFile()) for url in opened] == [notes]
    opener.reveal(str(notes))
    assert Path(opened[-1].toLocalFile()) == tmp_path
    parent.deleteLater()


def test_a_sent_message_with_chips_and_an_image_answer_in_a_narrow_dock(
    assistant, model, opened, tmp_path, wait
):
    from thzdaq_gui.chat_widgets import Chip
    from thzdaq_gui.docks.assistant import AssistantWidget, ImageItem
    from thzdaq_gui.image_viewer import ImageViewer

    model.drawing = png(512, 384, b"\xe0\x70\x20")
    model.replies = [DRAW, says("Here is the **red square**.")]
    notes = tmp_path / "notes.txt"
    notes.write_text("T_rx = 50 K at 220 GHz")
    widget = AssistantWidget(assistant)
    widget.resize(320, 700)
    widget.show()
    assistant.send(
        "draw it",
        [Attachment.of_file(notes), Attachment.image(png(64, 48, b"\x20\x80\xe0"))],
    )
    wait(lambda: not assistant.busy())
    (shown,) = widget.findChildren(ImageItem)
    wait(lambda: shown.image() is not None)
    assert shown.shown(shown.width()).width() <= shown.width() <= 320
    assert not widget.scroll.horizontalScrollBar().isVisible()
    shot(widget, "assistant_image_answer")
    file_chip, image_chip = widget.findChildren(Chip)
    QTest.mouseClick(file_chip, Qt.LeftButton, pos=QPoint(4, 4))
    assert [Path(url.toLocalFile()) for url in opened] == [notes]
    QTest.mouseClick(image_chip, Qt.LeftButton, pos=QPoint(4, 4))
    QTest.mouseClick(shown, Qt.LeftButton, pos=QPoint(20, 20))
    viewers = widget.findChildren(ImageViewer)
    assert [v.shown.name for v in viewers] == ["pasted.png", "a red square"]
    assert viewers[1].image() is shown.image()  # decoded once
    for viewer in viewers:
        viewer.close()
    widget.close()
