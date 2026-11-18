"""The assistant's hints where the person types, against a model's server on
localhost (model_server): what is asked and taken without Qt, the owner of
the questions (answers streamed with what the model does meanwhile, pieces
taken whole, failures, cancelled ones dropped), the editor offscreen (a
change hunk by hunk with ✓ and ✗, the ghost and its busy mark, Ctrl+I's box
with what the model thinks and writes), Fix of a script's failed run, and
all of it off without a server."""

import os
import threading
from pathlib import Path

import pytest
from model_server import says, thinks
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from thzdaq_gui.assistant import hints
from thzdaq_gui.assistant.provider import Provider
from thzdaq_gui.editor import CodeEditor
from thzdaq_gui.models.assistant import ProvidersModel
from thzdaq_gui.models.assistant import THINKING, WRITING
from thzdaq_gui.models.hints import NO_SERVER, WAITING, HintsModel, Stopped
from thzdaq_gui.review import Review, Source

# Pictures of the editor for a person to look at, when asked for (a folder)
SHOTS = os.environ.get("THZDAQ_SHOTS")
SCRIPT = 'bias = lab["sis_bias_1"]\nfor v in range(3):\n    print(v)\n'
FAILED = (
    "Traceback (most recent call last):\n"
    '  File "/x/scan.py", line 3, in <module>\n'
    "    print(w)\n"
    "NameError: name 'w' is not defined\n"
)


def shot(widget, name: str) -> None:
    if SHOTS:
        widget.grab().save(str(Path(SHOTS) / f"{name}.png"))


@pytest.fixture
def dropped(monkeypatch):
    """Changes not saved are dropped as the window closes."""
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)


@pytest.fixture(autouse=True)
def no_servers(app):
    """The settings outlive a test: the servers a test added go with it."""
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
def helper(session, providers):
    return HintsModel(session, providers)


@pytest.fixture
def editor(app, helper):
    editor = CodeEditor(None, helper)
    editor.pause.setInterval(1)  # the pause before a ghost: none in tests
    editor.resize(700, 300)
    editor.show()
    yield editor
    editor.close()
    editor.deleteLater()


def asked_text(model, index=-1):
    """What the user's message of a question to the model said."""
    return model.asked[index]["messages"][-1]["content"]


def hints_done() -> bool:
    """No question's thread runs any more."""
    return not any(t.name == "assistant hint" for t in threading.enumerate())


def heard_of(request):
    """What a request tells as it goes: each take's (thought, text)."""
    found = []
    request.progressed.connect(lambda thought, text: found.append((thought, text)))
    return found


# Without Qt: what is asked, what is taken
def test_code_is_taken_from_a_fenced_block_or_bare():
    assert hints.code_of("Here:\n```python\nx = 1\n\n```\nDone.") == "x = 1"
    assert hints.code_of("\n    y = 2\n") == "    y = 2"


def test_written_code_goes_at_the_cursor_or_in_place_of_the_selection():
    code = "a = 1\n    \nb = 2\n"
    at = code.index("    \n") + 4  # an indented empty line: whole lines
    assert hints.written(code, at, at, "```python\n    c = 3\n```") == (
        "a = 1\n    c = 3\nb = 2\n"
    )
    start = code.index("1")
    assert hints.written(code, start, start + 1, "max(1, 2)") == (
        "a = max(1, 2)\n    \nb = 2\n"
    )
    before = code.index("b")  # at the start of a line with code after it
    assert hints.written(code, before, before, "c = 3") == "a = 1\n    \nc = 3\nb = 2\n"


def test_a_ghost_is_what_follows_the_cursor():
    code = "for v in "
    assert hints.ghost_text(code, len(code), "range(3):") == "range(3):"
    assert hints.ghost_text(code, len(code), "for v in range(3):") == "range(3):"
    assert hints.ghost_text(code, len(code), "  \n") is None
    many = "\n".join(f"x{i}" for i in range(10))
    assert len(hints.ghost_text("", 0, many).split("\n")) == hints.GHOST_LINES


def test_a_fix_keeps_the_end_of_the_text():
    assert hints.fixed("x = 1\n", "```python\nx = 2\n```") == "x = 2\n"


def test_the_model_is_told_the_bench_and_where_the_code_is():
    system = hints.system("sis_bias_1: SIS bias")
    assert "sis_bias_1: SIS bias" in system and "m.sweep" in system
    asked = hints.write_messages(system, hints.IN_CONSOLE, "x", 1, 1, "read it")
    assert asked[0] == {"role": "system", "content": system}
    assert "lab = connect()" in asked[1]["content"]
    assert f"x{hints.CURSOR}" in asked[1]["content"]
    assert "read it" in asked[1]["content"]
    fix = hints.fix_messages(system, hints.IN_FILE, "x", "NameError", ["y = 1"])
    assert "y = 1" in fix[1]["content"] and "NameError" in fix[1]["content"]


# The owner of the questions
def test_a_question_streams_and_is_answered_in_the_gui_thread(helper, model, wait):
    model.replies = [thinks("Print v, it is the loop's.", "```python\nprint(v)\n```")]
    heard, ended = [], []
    request = helper.write(hints.IN_FILE, "x = 1\n", 6, 6, "print it", helper)
    assert request.phase == WAITING and request.asked == "print it"
    assert request.model == "qwen" and "local" in request.server
    progress = heard_of(request)
    request.answered.connect(heard.append)
    request.ended.connect(lambda: ended.append(True))
    wait(lambda: heard)
    assert heard == ["x = 1\nprint(v)"] and ended == [True]
    assert "".join(t for t, _ in progress) == "Print v, it is the loop's."
    assert "".join(x for _, x in progress) == "```python\nprint(v)\n```"
    (asked,) = model.asked
    assert asked["stream"] is True and "tools" not in asked
    assert "sis_bias_1" in asked["messages"][0]["content"]  # the bench's devices
    assert model.keys == ["Bearer secret"]


def test_a_request_tells_what_the_model_does_and_for_how_long(helper, model, app):
    model.held.clear()  # the model never answers in this test
    request = helper.write(hints.IN_FILE, "x\n", 2, 2, "anything", helper)
    request.began -= 4
    assert request.doing() == f"{WAITING}… 4 s"
    request.told.thought("Look at ")
    request.told.thought("the bias.")
    app.processEvents()
    assert request.phase == THINKING and request.thought == "Look at the bias."
    assert request.doing() == f"{THINKING}… 4 s" and request.text == ""
    request.told.heard("print(")
    app.processEvents()
    assert request.phase == WRITING and request.text == "print("
    request.cancel()
    model.held.set()


def test_pieces_reach_the_gui_thread_in_one_take(helper, model, app):
    """However many pieces came while the GUI thread was busy: one update,
    and the queue woke it once."""
    model.held.clear()
    request = helper.write(hints.IN_FILE, "x\n", 2, 2, "anything", helper)
    progress = heard_of(request)
    woken = []
    helper._arrived.connect(lambda told: woken.append(told))  # directly: each emit
    for _ in range(200):
        request.told.thought("hm ")
    for _ in range(300):
        request.told.heard("ab")
    assert len(woken) == 1 and progress == []
    app.processEvents()
    assert progress == [("hm " * 200, "ab" * 300)]
    assert request.phase == WRITING
    request.cancel()
    model.held.set()


def test_a_failure_is_told_and_a_cancelled_answer_dropped(helper, model, wait, app):
    model.status = 500
    failed, ended = [], []
    request = helper.ghost(hints.IN_FILE, "x", 1, helper)
    request.failed.connect(failed.append)
    request.ended.connect(lambda: ended.append(True))
    wait(lambda: failed)
    assert "500" in failed[0] and ended == [True]
    # Cancelled with pieces on their way: they are dropped, and the next one
    # the model sends stops its reply
    model.status = 200
    model.held.clear()
    model.replies = [thinks("long " * 50, "range(3):")]
    heard, ended = [], []
    request = helper.ghost(hints.IN_FILE, "x", 1, helper)
    progress = heard_of(request)
    request.answered.connect(heard.append)
    request.ended.connect(lambda: ended.append(True))
    wait(lambda: model.asked)
    told = request.told
    told.heard("late")
    request.cancel()
    assert ended == [True]  # at once
    with pytest.raises(Stopped):
        told.heard("later")
    model.held.set()
    wait(hints_done)
    assert heard == [] and progress == [] and ended == [True]


# The editor: a change hunk by hunk
def test_the_editor_shows_a_change_hunk_by_hunk(editor):
    editor.setPlainText("a = 1\nb = 2\nc = 3\nd = 4\n")
    ended = []
    editor.review_ended.connect(lambda: ended.append(editor.toPlainText()))
    editor.show_review(
        Review(editor.toPlainText(), "a = 1\nb = 20\nc = 3\nc2 = 5\n", Source.PROPOSED)
    )
    assert editor.isReadOnly() and not editor.reviewBar.isHidden()
    assert editor.reviewBar.label.text() == "Proposed by the assistant · 2 changes"
    assert editor.toPlainText() == "a = 1\nb = 2\nb = 20\nc = 3\nd = 4\nc2 = 5"
    assert [b.index for b in editor.hunkButtons] == [0, 1]
    assert all(b.isVisible() for b in editor.hunkButtons)
    marks = editor.extraSelections()
    assert any(m.format.fontStrikeOut() for m in marks)  # what goes is struck out
    shot(editor, "review")
    QTest.keyClicks(editor, "typed")  # nothing is typed while it is looked at
    assert "typed" not in editor.toPlainText()
    editor.hunkButtons[1].take.click()
    assert editor.review is not None and len(editor.hunkButtons) == 1
    assert editor.code() == "a = 1\nb = 2\nc = 3\nc2 = 5\n"
    editor.hunkButtons[0].leave.click()
    assert editor.review is None and not editor.isReadOnly()
    assert ended == ["a = 1\nb = 2\nc = 3\nc2 = 5\n"]
    assert editor.reviewBar.isHidden() and editor.hunkButtons == []


def test_all_hunks_are_taken_or_left_at_once(editor):
    editor.setPlainText("a\nb\n")
    editor.show_review(Review("a\nb\n", "x\nb\ny\n", Source.OUTSIDE))
    assert editor.reviewBar.takeAll.text() == "Keep all"
    assert editor.code() == "x\nb\ny\n"  # made already: kept until undone
    editor.reviewBar.leaveAll.click()
    assert editor.toPlainText() == "a\nb\n" and editor.review is None


def test_a_proposal_for_a_text_changed_since_is_not_shown(editor):
    editor.setPlainText("a\n")
    assert editor.propose("other\n", "b\n") is not None
    assert editor.propose("a\n", "a\n") is not None  # it changes nothing
    assert editor.review is None
    assert editor.propose("a\n", "b\n") is None and editor.review is not None


# The ghost
def test_a_ghost_comes_after_a_pause_and_tab_takes_it(editor, model, wait):
    model.replies = [says("range(3):")]
    QTest.keyClicks(editor, "for v in ")
    wait(lambda: editor.ghost is not None)
    assert editor.ghost == "range(3):" and not editor.ghostMark.isVisible()
    assert asked_text(model).endswith(
        f"for v in {hints.CURSOR}\n```\n\nComplete the code at {hints.CURSOR}: "
        f"answer with what follows it only, at most {hints.GHOST_LINES} lines, "
        "nothing when nothing fits."
    )
    shot(editor, "ghost")
    QTest.keyClick(editor, Qt.Key_Tab)
    assert editor.toPlainText() == "for v in range(3):" and editor.ghost is None


def test_esc_or_typing_drops_a_ghost(editor, model, wait):
    model.replies = [says("range(3):"), says("range(3):")]
    QTest.keyClicks(editor, "for v in ")
    wait(lambda: editor.ghost is not None)
    QTest.keyClick(editor, Qt.Key_Escape)
    assert editor.ghost is None and editor.toPlainText() == "for v in "
    editor.pause.setInterval(60_000)  # no other ghost asked in this test
    QTest.keyClicks(editor, "x")
    editor.pause.setInterval(1)
    editor.ask_ghost()
    wait(lambda: editor.ghost is not None)
    QTest.keyClicks(editor, "y")
    assert editor.ghost is None and editor.toPlainText() == "for v in xy"


def test_a_ghost_for_text_typed_before_is_never_shown(editor, helper, model, wait):
    model.held.clear()  # the model thinks
    model.replies = [says("stale")]
    QTest.keyClicks(editor, "x = ")
    wait(lambda: model.asked)
    editor.pause.setInterval(60_000)
    QTest.keyClicks(editor, "1")  # typed since: the question goes
    model.held.set()
    wait(hints_done)
    assert editor.ghost is None and editor.asked_ghost is None


def test_a_ghost_asked_shows_a_busy_mark_only(editor, model, wait):
    model.held.clear()
    model.replies = [thinks("hm", "range(3):")]
    QTest.keyClicks(editor, "for v in ")
    wait(lambda: model.asked)
    mark = editor.ghostMark
    assert mark.isVisible() and "qwen" in mark.toolTip()
    caret = editor.cursorRect()
    assert mark.geometry().left() > caret.left()  # where the ghost would show
    assert abs(mark.geometry().center().y() - caret.center().y()) <= 1
    assert not editor.askBox.isVisible()  # quiet: no box, no thought shown
    shot(editor, "ghost_asked")
    model.held.set()
    wait(lambda: editor.ghost is not None)
    assert not mark.isVisible()
    # A ghost that fails: the mark goes, nothing is told
    QTest.keyClick(editor, Qt.Key_Escape)
    model.status = 500
    QTest.keyClicks(editor, "x")
    wait(lambda: len(model.asked) == 2)
    wait(lambda: editor.asked_ghost is None)
    assert not mark.isVisible() and editor.ghost is None
    assert not editor.askBox.isVisible()


def test_moving_the_cursor_drops_a_ghost_asked(editor, model, wait):
    model.held.clear()
    editor.setPlainText("a = 1\n")
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    QTest.keyClicks(editor, "b = ")
    wait(lambda: model.asked)
    editor.pause.setInterval(60_000)
    editor.moveCursor(editor.textCursor().MoveOperation.Start)
    assert editor.asked_ghost is None and not editor.ghostMark.isVisible()
    model.held.set()


# Ctrl+I
def test_ctrl_i_shows_what_the_model_does_until_the_proposal(editor, model, wait):
    editor.setPlainText(SCRIPT)
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    model.held.clear()  # the model is slow: the box shows what it does
    model.replies = [says("```python\nprint(bias.voltage)\n```")]
    QTest.keyClick(editor, Qt.Key_I, Qt.ControlModifier)
    QTest.keyClicks(editor.askBox.field, "print the voltage")
    QTest.keyClick(editor.askBox.field, Qt.Key_Return)
    box = editor.askBox
    request = editor.asked_code
    assert box.request is request and box.field.isReadOnly()
    assert box.spinner.isVisible() and box.doing.text() == f"{WAITING}… 0 s · qwen"
    assert "qwen" in box.spinner.toolTip() and "local" in box.doing.toolTip()
    assert not box.preview.isVisible() and not box.thoughtButton.isVisible()
    # It thinks: the thought comes folded, a click opens it
    request.began -= 4
    request.told.thought("The voltage of bias_1 is read with bias.voltage; ")
    request.told.thought("the loop printed v, so print it after the loop.")
    wait(lambda: request.phase == THINKING)
    assert box.doing.text() == f"{THINKING}… 4 s · qwen"
    assert box.thoughtButton.isVisible() and not box.thoughtView.isVisible()
    shot(editor, "ask_thinking")
    box.thoughtButton.click()
    assert box.thoughtView.isVisible()
    assert box.thoughtView.toPlainText().endswith("so print it after the loop.")
    box.thoughtButton.click()
    # It writes: the code so far in a preview that grows
    request.began -= 2
    request.told.heard("```python\nfor v in range(3):\n")
    wait(lambda: request.phase == WRITING)
    assert box.doing.text() == f"{WRITING}… 6 s · qwen"
    assert box.preview.isVisible() and box._lines == 3
    first = box.preview.height()
    request.told.heard("    print(v)\n")
    wait(lambda: box._lines == 4)
    assert box.preview.height() > first
    assert box.preview.toPlainText() == "```python\nfor v in range(3):\n    print(v)\n"
    shot(editor, "ask_writing")
    # Its end: the proposal, hunk by hunk
    model.held.set()
    wait(lambda: editor.review is not None)
    assert not box.isVisible() and not box.ticker.isActive()
    assert editor.asked_code is None


def test_a_long_preview_follows_its_end_within_its_lines(editor, model, wait):
    model.held.clear()
    QTest.keyClick(editor, Qt.Key_I, Qt.ControlModifier)
    QTest.keyClicks(editor.askBox.field, "many lines")
    QTest.keyClick(editor.askBox.field, Qt.Key_Return)
    box = editor.askBox
    for line in range(40):
        editor.asked_code.told.heard(f"x{line} = {line}\n")
    wait(lambda: box.preview.isVisible())
    assert box.geometry().bottom() <= editor.viewport().height()
    bar = box.preview.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == bar.maximum()
    QTest.keyClick(box.field, Qt.Key_Escape)  # Esc stops it
    assert not box.isVisible() and editor.asked_code is None
    model.held.set()


def test_ctrl_i_asks_for_code_that_comes_as_a_proposal(editor, model, wait):
    editor.setPlainText(SCRIPT)
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    model.replies = [says("```python\nprint(bias.voltage)\n```")]
    QTest.keyClick(editor, Qt.Key_I, Qt.ControlModifier)
    assert editor.askBox.isVisible()
    QTest.keyClicks(editor.askBox.field, "print the voltage")
    QTest.keyClick(editor.askBox.field, Qt.Key_Return)
    QTest.keyClicks(editor.askBox.field, "more")  # while it writes: nowhere
    wait(lambda: editor.review is not None)
    assert len(model.asked) == 1  # no ghost: nothing was typed in the text
    assert "print the voltage" in asked_text(model)
    assert f"    print(v)\n{hints.CURSOR}" in asked_text(model)
    assert not editor.askBox.isVisible()
    editor.hunkButtons[0].take.click()
    assert editor.toPlainText() == SCRIPT + "print(bias.voltage)"


def test_esc_or_close_drops_the_question(editor, model, wait):
    model.held.clear()
    QTest.keyClick(editor, Qt.Key_I, Qt.ControlModifier)
    QTest.keyClicks(editor.askBox.field, "anything")
    QTest.keyClick(editor.askBox.field, Qt.Key_Return)
    wait(lambda: model.asked)
    QTest.keyClick(editor.askBox.field, Qt.Key_Escape)
    assert not editor.askBox.isVisible() and editor.asked_code is None
    QTest.keyClick(editor, Qt.Key_I, Qt.ControlModifier)
    QTest.keyClick(editor.askBox.field, Qt.Key_Return)  # the words kept: again
    assert editor.asked_code is not None
    editor.askBox.closeButton.click()
    assert not editor.askBox.isVisible() and editor.asked_code is None
    assert not editor.askBox.ticker.isActive()
    model.held.set()


def test_a_failure_is_told_in_the_field(editor, model, wait):
    model.status = 401
    QTest.keyClick(editor, Qt.Key_I, Qt.ControlModifier)
    QTest.keyClicks(editor.askBox.field, "anything")
    QTest.keyClick(editor.askBox.field, Qt.Key_Return)
    wait(lambda: "refused" in editor.askBox.status.text())
    assert not editor.askBox.field.isReadOnly()  # asked again as it is
    assert not editor.askBox.spinner.isVisible() and editor.asked_code is None


# Fix of a script's failed run, in its tab
def test_fix_mends_a_script_by_its_failed_run(window, wait, model, tmp_path, dropped):
    window.providers.save(Provider("local", model.url, "qwen"), "secret")
    path = tmp_path / "scan.py"
    path.write_text("for v in range(3):\n    print(w)\n", encoding="utf-8")
    window.code.open(path)
    widget = window.code.widgets[str(path.resolve())]
    assert not widget.fixButton.isEnabled()  # nothing failed yet
    widget.output.show_whole("0\n" + FAILED)
    assert widget.fixButton.isEnabled() and widget.askButton.isEnabled()
    fixed = says("```python\nfor v in range(3):\n    print(v)\n```")
    model.replies = [fixed, fixed]  # the first is asked, then stopped
    model.held.clear()
    widget.fixButton.click()
    box = widget.editor.askBox
    assert box.isVisible() and box.spinner.isVisible()  # what it does meanwhile
    assert box.field.text() == "Fix: NameError: name 'w' is not defined"
    assert not widget.fixButton.isEnabled()
    QTest.keyClick(box.field, Qt.Key_Escape)  # stopped: Fix again
    assert not box.isVisible() and widget.fixing is None
    assert widget.fixButton.isEnabled()
    widget.fixButton.click()
    model.held.set()
    wait(lambda: widget.editor.review is not None)
    assert widget.fixButton.isEnabled() and len(model.asked) == 2
    window.resize(1200, 800)
    shot(window.code.tabs, "editor_fix_review")
    assert "NameError: name 'w' is not defined" in asked_text(model)
    assert widget.editor.review.source is Source.PROPOSED
    widget.editor.reviewBar.takeAll.click()
    assert widget.text == "for v in range(3):\n    print(v)\n"
    assert widget.unsaved()  # the person saves it


# Without a server
def test_without_a_server_the_hints_are_off_and_say_why(window, model, wait, dropped):
    assert not window.hints.available()
    window.code.open_text("draft", "x = 1\n")
    (widget,) = window.code.widgets.values()
    assert not widget.askButton.isEnabled() and widget.askButton.toolTip() == NO_SERVER
    assert not widget.fixButton.isEnabled() and widget.fixButton.toolTip() == NO_SERVER
    editor = widget.editor
    editor.pause.setInterval(1)
    QTest.keyClicks(editor, "y = ")
    QTest.keyClick(editor, Qt.Key_I, Qt.ControlModifier)
    assert not editor.askBox.isVisible() and editor.asked_ghost is None
    assert model.asked == []
    console = window.consoles.new()
    assert not console.askButton.isEnabled() and not console.fixButton.isEnabled()
    # A server added: on at once
    window.providers.save(Provider("local", model.url, "qwen"), "secret")
    assert widget.askButton.isEnabled() and console.askButton.isEnabled()
