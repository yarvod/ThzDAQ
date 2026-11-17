"""Widgets of the chat (offscreen): a message that grows as the model writes
it is extended, never rendered anew, and ends as the whole text would show."""

import pytest
from PySide6.QtGui import QTextCursor

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
