"""Widgets of the chat (offscreen): a message that grows as the model writes
it is extended, never rendered anew, and ends as the whole text would show."""

import pytest
from PySide6.QtGui import QIcon, QTextCursor

SAMPLES = {
    "paragraphs": "One **bold** line.\n\nTwo `code` line.\n\nThree.",
    "headings": "# Title\n\nText under it.\n\n## Sub\n\nMore.",
    "fence": "Before.\n\n```python\nx = 1\n\ny = 2\n```\n\nAfter.",
    "bullets": "- a\n- b\n\n- c\n\nText.",
    "numbers": "1. one\n2. two\n\n3. three\n\nText.",
    "nested": "- a\n  - a1\n\n  continued\n- b\n\nEnd.",
    "table": "| a | b |\n|---|---|\n| 1 | 2 |\n\nAfter the table.",
    "quote": "> quoted\n> more\n\nAfter.",
    "link": "See [the docs](https://example.com).\n\n~~~\ncode\n~~~\n\nEnd.",
}


def blocks(view):
    """What a reader sees of each block: its text, heading, code and list."""
    found = []
    block = view.document().begin()
    while block.isValid():
        shape = block.blockFormat()
        listed = block.textList()
        found.append(
            (
                block.text(),
                shape.headingLevel(),
                shape.background().color().name(),
                listed.format().style() if listed else None,
                listed.itemText(block) if listed else None,
            )
        )
        block = block.next()
    return found


@pytest.mark.parametrize("name", SAMPLES)
def test_a_streamed_answer_ends_as_the_whole_text(app, name):
    from thzdaq_gui.chat_widgets import MessageView

    text = SAMPLES[name]
    streamed, whole = MessageView(markdown=True), MessageView(markdown=True)
    for end in range(1, len(text) + 1, 3):
        streamed.show_text(text[:end])
    streamed.show_text(text)
    whole.show_text(text)
    assert blocks(streamed) == blocks(whole)
    assert streamed.height() == whole.height()


def test_what_is_shown_stays_as_more_comes(app):
    """A person may select in an answer while it is written: the paragraphs
    already shown are not made anew, so the selection stays."""
    from thzdaq_gui.chat_widgets import MessageView

    text = "# Gap\n\nThe gap is at **2.8 mV**.\n\n```\nx = 1\n```\n\nRn is 21 Ω."
    for markdown in (True, False):
        view = MessageView(markdown=markdown)
        view.resize(300, 100)
        view.show_text(text[:12])
        cursor = view.textCursor()
        cursor.setPosition(0 if markdown else 2)
        cursor.setPosition(3 if markdown else 5, QTextCursor.KeepAnchor)
        view.setTextCursor(cursor)
        for end in range(13, len(text) + 1):
            view.show_text(text[:end])
        assert view.textCursor().selectedText() == "Gap"
        assert view.text().endswith("Rn is 21 Ω.")


def test_text_that_is_not_a_continuation_is_shown_anew(app):
    from thzdaq_gui.chat_widgets import MessageView

    view = MessageView(markdown=True)
    view.show_text("First answer.\n\nWith two paragraphs.")
    view.show_text("Another.")
    assert view.text() == "Another."


def test_the_context_ring_fills_and_warms_as_the_context_fills(app):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtWidgets import QApplication
    from thzdaq_gui import theme
    from thzdaq_gui.chat_widgets import ContextRing

    ring = ContextRing()
    hovered = []
    ring.hovered.connect(hovered.append)
    assert ring.share() is None and ring.color() == theme.MUTED  # no limit known
    ring.show_share(0.17)
    assert ring.color() == theme.MUTED
    ring.show_share(0.75)
    assert ring.color() == theme.ACCENT
    ring.show_share(0.95)
    assert ring.color() == theme.BAD
    at = QPointF(1, 1)
    QApplication.sendEvent(ring, QEnterEvent(at, at, at))
    QApplication.sendEvent(ring, QEvent(QEvent.Leave))
    assert hovered == [True, False]
    assert ring.grab().width() == ring.SIDE  # it paints


def test_buttons_flow_into_rows_and_wrap_their_words_within_the_width(app):
    from PySide6.QtWidgets import QWidget
    from thzdaq_gui.chat_widgets import Flow, WrapButton

    holder = QWidget()
    flow = Flow(holder)
    short = [WrapButton(QIcon(), name) for name in ("Yes", "No")]
    long = WrapButton(
        QIcon(),
        "Yes, and don't ask again for commands that start with "
        "`python -m thzdaq_api.kernel --connection-file /a/very/long/path`",
    )
    for button in short + [long]:
        flow.addWidget(button)
    assert flow.minimumSize().width() < 120  # the long one asks no more than a word
    holder.resize(300, flow.heightForWidth(300))
    holder.show()
    app.processEvents()
    yes, no = short
    assert yes.y() == no.y() and no.x() > yes.x()  # short ones share a row
    assert long.y() > yes.y() and long.width() == 300  # a row of its own, wrapped
    assert long.height() > 2 * long.fontMetrics().lineSpacing()
    assert all(b.geometry().right() < 300 for b in short + [long])


# A command an agent runs: a PowerShell here-string with a script in it
COMMAND = "@'\nimport glob, json\n" + "x = 1\n" * 40 + "'@ | python -"


def test_a_cut_line_of_text_of_many_lines_is_one_line(app):
    from thzdaq_gui.chat_widgets import ElidedLabel

    label = ElidedLabel(COMMAND)
    one = ElidedLabel("one line")
    assert label.sizeHint().height() == one.sizeHint().height()
    assert label.minimumSizeHint().height() == one.minimumSizeHint().height()
    assert label.text() == COMMAND and label.toolTip() == COMMAND  # whole
    label.setText("short")
    assert label.text() == "short"
