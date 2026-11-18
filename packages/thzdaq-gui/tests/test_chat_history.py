"""The assistant's chats kept (offscreen): the files of the built-in chat
(history.Shelf, Recorder), a kept chat opened in the view model and gone on
with, and the History page of the dock."""

import itertools
import json
import threading
import time
from typing import List

import pytest
from model_server import says, thinks
from test_assistant_dock import FakeChat, built_in, kinds
from thzdaq_gui.assistant import builtin
from thzdaq_gui.assistant.attachments import Attachment, content
from thzdaq_gui.assistant.chat import Call, Kept, Outcome, Said, Used
from thzdaq_gui.assistant.history import CHAT, Recorder, Shelf, title_of
from thzdaq_gui.assistant.provider import Provider
from thzdaq_gui.models.assistant import (
    THINKING,
    AssistantModel,
    CodexSettingsModel,
    InstructionsModel,
    Kind,
    ProvidersModel,
    ago,
)

IMAGE = b"\x89PNG\r\n\x1a\n not quite a picture"


@pytest.fixture(autouse=True)
def no_servers(app):
    """The servers a test added go with it (the settings outlive it)."""
    yield
    providers = ProvidersModel()
    for provider in providers.all():
        providers.remove(provider.name)


@pytest.fixture
def providers(model):
    providers = ProvidersModel()
    providers.save(Provider("local", model.url, "qwen"), "secret")
    return providers


@pytest.fixture
def instructions(app):
    return InstructionsModel()


@pytest.fixture
def assistant(session, providers, instructions):
    assistant = built_in(session, providers, instructions)
    yield assistant
    assistant.close()


@pytest.fixture
def fake(session, providers, instructions):
    chat = FakeChat()
    assistant = AssistantModel(
        session, providers, instructions, CodexSettingsModel(), [chat]
    )
    yield chat, assistant
    assistant.close()


class Quiet:
    """A turn's own listener that hears nothing."""

    def __getattr__(self, name):
        return lambda *told: None


class Told:
    """What a kept chat told as it was opened (chat.Replay), in order."""

    def __init__(self):
        self.told: List[tuple] = []
        self.done = threading.Event()

    def began(self, said):
        self.told.append(("began", said))

    def said(self, said):
        self.told.append(("said", said))

    def asking(self):
        self.told.append(("asking",))

    def taken(self, count):
        self.told.append(("taken", count))

    def thought(self, piece, seconds=None):
        self.told.append(("thought", piece, seconds is not None))

    def text(self, piece):
        self.told.append(("text", piece))

    def called(self, call):
        self.told.append(("called", call))

    def progress(self, call, done, total):
        self.told.append(("progress", call))

    def answered(self, call, text, failed):
        self.told.append(("answered", call, text, failed))

    def usage(self, used):
        self.told.append(("usage", used))

    def ended(self, outcome, why, seconds=None):
        self.told.append(("ended", outcome, why, seconds is not None))

    def opened(self, why=""):
        self.told.append(("opened", why))
        self.done.set()


def listed(shelf: Shelf, workspace) -> List[Kept]:
    """The chats of a workspace, once all asked of the shelf before is done."""
    found, done = [], threading.Event()
    shelf.chats(workspace, lambda chats: found.extend(chats) or done.set())
    assert done.wait(5)
    return found


def test_a_kept_chat_is_told_again_as_it_went_with_its_messages(tmp_path):
    shelf = Shelf(tmp_path / "chats")
    image = Attachment.image(IMAGE)
    said = Said("Look at this plot\nand tell me where the gap is", (image,))
    chat = shelf.new(tmp_path / "bench", said)
    assert chat.title == "Look at this plot"
    messages = [{"role": "user", "content": content(said.text, said.attachments)}]
    first = Recorder(shelf, chat, said, (), Quiet(), lambda: list(messages))
    first.asking()
    for piece in ("h", "mm"):
        first.thought(piece)
    for piece in ("It is ", "at 2.8 mV."):
        first.text(piece)
    first.called(Call("c1", "read_device", {"ref": "sis_bias_1"}))
    first.progress("c1", 1, 2)
    first.answered("c1", "sis_bias_1: 0 V", False)
    first.usage(Used(100, 10, 4, 110))
    messages.append({"role": "assistant", "content": "It is at 2.8 mV."})
    first.ended(Outcome.ANSWERED, "")
    first.text(" and late")  # told after it was kept: not kept

    # Stopped by the person, with what was said meanwhile
    again = Said("again")
    since = len(messages)
    second = Recorder(shelf, chat, again, (), Quiet(), lambda: messages[since:])
    messages.append({"role": "user", "content": "again"})
    second.asking()
    second.text("half")
    second.called(Call("c2", "list_devices"))
    assert second.said(Said("and faster"))
    second.finish(Outcome.STOPPED, "")
    assert not second.said(Said("too late"))  # it goes with the next turn
    second.ended(Outcome.STOPPED, "")  # its thread ends after: kept once

    restored, told = [], Told()
    shelf.open(chat, restored.extend, told)
    assert told.done.wait(5)
    assert restored == messages  # the image within, as it went
    assert told.told == [
        ("began", said),
        ("asking",),
        ("thought", "hmm", True),
        ("text", "It is at 2.8 mV."),
        ("called", Call("c1", "read_device", {"ref": "sis_bias_1"})),
        ("answered", "c1", "sis_bias_1: 0 V", False),
        ("usage", Used(100, 10, 4, 110)),
        ("ended", Outcome.ANSWERED, "", True),
        ("began", again),
        ("asking",),
        ("text", "half"),
        ("called", Call("c2", "list_devices")),
        ("said", Said("and faster")),
        ("ended", Outcome.STOPPED, "", True),
        ("opened", ""),
    ]
    folder = shelf.folder(chat)
    kept = (folder / CHAT).read_text(encoding="utf-8")
    assert len(kept.splitlines()) == 3  # its version, then a line per turn
    assert "base64" not in kept  # the image is a file beside it, once
    assert [path.read_bytes() for path in folder.glob("*.png")] == [IMAGE]


def test_chats_are_listed_by_workspace_the_newest_first(tmp_path, monkeypatch):
    clock = itertools.count(1_000_000.0)
    monkeypatch.setattr(time, "time", lambda: next(clock))
    shelf = Shelf(tmp_path / "chats")
    bench, other = tmp_path / "a" / "bench", tmp_path / "b" / "bench"
    first = shelf.new(bench, Said("first\nof all"))
    second = shelf.new(bench, Said("second"))
    shelf.new(other, Said("", (Attachment.image(IMAGE),)))  # a namesake folder
    shelf.rename(second, "Renamed")
    turn = Recorder(shelf, first, None, (), Quiet(), list)
    turn.ended(Outcome.ANSWERED, "")  # spoken in last
    assert [chat.title for chat in listed(shelf, bench)] == ["first", "Renamed"]
    assert [chat.title for chat in listed(shelf, other)] == ["pasted.png"]
    assert listed(shelf, tmp_path / "none") == []


def test_titles_and_how_long_ago():
    assert title_of(Said("  \n" + "x" * 100)) == "x" * 79 + "…"
    assert title_of(None) == "Chat"
    now = 1_000_000.0
    assert ago(now - 30, now) == "just now"
    assert ago(now - 300, now) == "5 min ago"
    assert ago(now - 3 * 3600, now) == "3 h ago"
    assert ago(now - 30 * 3600, now) == "yesterday"
    assert ago(now - 4 * 86400, now) == "4 days ago"


def test_an_opened_chat_goes_on_with_its_messages_and_a_prompt_made_anew(
    assistant, session, model, wait, monkeypatch
):
    made = []
    prompt = builtin.system_prompt
    monkeypatch.setattr(
        builtin, "system_prompt", lambda *given: made.append(1) or prompt(*given)
    )
    model.replies = [says("One."), says("Two.")]
    assistant.send("first")
    wait(lambda: not assistant.busy())
    assistant.new_chat()
    assistant.find_chats()
    wait(lambda: assistant.chats())
    (kept,) = assistant.chats()
    assert kept.title == "first" and kept.workspace == session.workspace.folder
    changed = []
    assistant.item_changed.connect(changed.append)
    assistant.open_chat(kept.id)
    assert assistant.current_chat() == kept.id
    wait(lambda: assistant.items)
    assert kinds(assistant) == [Kind.PERSON, Kind.ANSWER]
    assert [i.text for i in assistant.items[:2]] == ["first", "One."]
    assert assistant.items[2].text.endswith(" s · 1 step · 1.2k in · 30 out")
    assert len(changed) == len(set(changed))  # each item told once
    assert len(made) == 1
    assistant.send("second")
    wait(lambda: not assistant.busy())
    assert len(made) == 2  # the bench may have changed meanwhile
    asked = model.asked[-1]["messages"]
    assert asked[0]["role"] == "system"
    assert [(m["role"], m["content"]) for m in asked[1:]] == [
        ("user", "first"),
        ("assistant", "One."),
        ("user", "second"),
    ]
    assert [i.text for i in assistant.items if i.kind is Kind.ANSWER] == [
        "One.",
        "Two.",
    ]


def test_a_turn_is_kept_whole_once_over_off_the_gui_thread(
    assistant, session, model, wait, monkeypatch
):
    kept = []
    append = Shelf._append

    def appended(shelf, chat, turn):
        kept.append((threading.current_thread() is threading.main_thread(), turn))
        append(shelf, chat, turn)

    monkeypatch.setattr(Shelf, "_append", appended)
    answer = "The gap is at 2.8 mV. " * 20  # streamed 5 letters at a time
    model.replies = [thinks("Let me see.", answer)]
    assistant.send("where is the gap?")
    wait(lambda: not assistant.busy())
    model.held.clear()  # the next answer waits: it is stopped meanwhile
    assistant.send("and the current?")
    wait(lambda: len(model.asked) == 2)
    assistant.stop()
    model.held.set()
    chat = assistant.mode.chat
    listed(chat.shelf, session.workspace.folder)  # all asked before is done
    assert [on_gui for on_gui, _ in kept] == [False, False]
    assert [turn.outcome for _, turn in kept] == [Outcome.ANSWERED, Outcome.STOPPED]
    lines = (chat.shelf.folder(chat.current()) / CHAT).read_text().splitlines()
    first, stopped = (json.loads(line) for line in lines[1:])
    assert [told[0] for told in first["told"]] == ["asking", "thought", "text", "usage"]
    assert first["told"][2] == ["text", answer]  # the pieces joined
    assert stopped["said"]["text"] == "and the current?"
    assert stopped["ended"] == "stopped"


def test_an_opened_chat_comes_back_whole_in_one_take_by_the_live_handlers(
    fake, session, app
):
    chat, assistant = fake
    chat.kept = [Kept("k1", "Bias", 1000.0, session.workspace.folder)]
    assistant.find_chats()
    app.processEvents()
    assistant.send("before")  # a turn of the chat shown runs
    assistant.open_chat("k1")
    assert chat.stopped == 1 and not assistant.items and not assistant.busy()
    replay = chat.replay
    assistant.send("meanwhile")  # waits for the chat to open

    def tell():  # from the chat's thread
        replay.began(Said("bias?"))
        replay.asking()
        replay.thought("hmm", 2.0)
        replay.called(Call("c1", "read_device", {"ref": "sis_bias_1"}))
        replay.answered("c1", "sis_bias_1: 0 V", False)
        replay.text("It is ")
        replay.text("0 V.")
        replay.usage(Used(100, 10, 0, 110))
        replay.ended(Outcome.ANSWERED, "", 3.0)
        replay.began(Said("sweep it"))
        replay.asking()
        replay.said(Said("faster"))
        replay.ended(Outcome.STOPPED, "", 1.0)

    told = threading.Thread(target=tell)
    told.start()
    told.join()
    app.processEvents()
    assert not assistant.items  # gathered, not handed over yet
    added, changed = [], []
    assistant.added.connect(added.append)
    assistant.item_changed.connect(changed.append)
    replay.opened()
    app.processEvents()
    items = assistant.items
    assert [i.kind for i in items] == [
        Kind.PERSON, Kind.THOUGHT, Kind.CALL, Kind.ANSWER, Kind.STATS,
        Kind.PERSON, Kind.PERSON, Kind.NOTE, Kind.STATS, Kind.PERSON,
    ]  # fmt: skip
    assert added == list(range(len(items)))
    assert len(changed) == len(set(changed))
    thought, call, answer, stats = items[1:5]
    assert thought.thought_title() == "Thought for 2 s"
    assert call.summary() == "read_device sis_bias_1 → done"
    assert answer.text == "It is 0 V."
    assert stats.text == "3.0 s · 1 step · 100 in · 10 out"
    assert items[6].text == "faster" and items[6].unsent
    assert items[7].text == "Stopped." and items[8].text == "1.0 s · 1 step"
    assert assistant.usage.read == 100 and assistant.phase == THINKING
    # what was sent meanwhile went once it opened
    assert chat.started == [Said("before"), Said("meanwhile")] and assistant.busy()


def test_the_history_page_searches_opens_goes_back_and_renames(
    fake, session, app, tmp_path
):
    from thzdaq_gui.docks.assistant import AssistantWidget, Bubble

    chat, assistant = fake
    folder = session.workspace.folder
    now = time.time()
    chat.kept = [
        Kept("k2", "Plot the I-V curve", now - 125, folder),
        Kept("k1", "Bias sweep", now - 2 * 86400 - 5, folder),
    ]
    widget = AssistantWidget(assistant)
    assistant.send("hello")
    chat.turn.text("Hi.")
    chat.turn.ended(Outcome.ANSWERED, "")
    app.processEvents()
    shown = list(widget.shown)
    page = widget.historyPage

    def rows():
        found = (
            page.list.topLevelItem(i) for i in range(page.list.topLevelItemCount())
        )
        return [(item.text(0), item.text(1)) for item in found]

    widget.historyButton.click()
    assert widget.pages.currentWidget() is page and chat.listed == [folder]
    app.processEvents()
    assert rows() == [("Plot the I-V curve", "2 min ago"), ("Bias sweep", "2 days ago")]
    page.search.setText("BIAS")
    assert rows() == [("Bias sweep", "2 days ago")]
    page.search.setText("nothing like it")
    assert rows() == [] and not page.empty.isHidden()
    page.search.clear()

    edited = page.list.topLevelItem(1)
    edited.setText(0, "Bias  sweep at 4 K ")  # as an edit in place ends
    assert chat.renamed == [("k1", "Bias sweep at 4 K")]
    assert [c.title for c in assistant.chats()] == [
        "Plot the I-V curve",
        "Bias sweep at 4 K",
    ]
    assert page.list.topLevelItem(1) is edited  # the row stays

    widget.historyButton.click()  # back to the chat, as it was
    assert widget.pages.currentWidget() is widget.chatPage
    assert widget.shown == shown and all(w.parent() for w in shown)

    widget.historyButton.click()
    page.list.itemClicked.emit(page.list.topLevelItem(0), 0)
    assert widget.pages.currentWidget() is widget.chatPage
    assert not widget.historyButton.isChecked()
    assert chat.shown == chat.kept[0] and not widget.shown
    chat.replay.began(Said("plot it"))
    chat.replay.text("Here.")
    chat.replay.ended(Outcome.ANSWERED, "", 1.0)
    chat.replay.opened()
    app.processEvents()
    bubbles = [w for w in widget.shown if isinstance(w, Bubble)]
    assert [b.label.text() for b in bubbles] == ["plot it", "Here."]
    widget.historyButton.click()
    app.processEvents()
    assert [page.list.topLevelItem(i).font(0).bold() for i in range(2)] == [
        True,  # the chat shown
        False,
    ]
    other = tmp_path / "other"
    other.mkdir()
    session.workspace.open(other)  # its chats are listed now
    assert chat.listed[-1] == other.resolve()
    widget.close()
