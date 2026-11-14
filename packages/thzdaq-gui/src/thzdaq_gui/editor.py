"""A Python editor for scripts: line numbers, colours by pygments, indents kept
as Python wants them, a popup of completions, the lines a check finds wrong
marked. What completes a word is given (the dock of a script asks jedi and
the bench); the editor only shows it.

Keys: Tab indents (four spaces, the lines of a selection too), Shift+Tab
dedents, Enter keeps the indent (one more after a colon), Ctrl+Space or a
dot asks for completions, Ctrl+/ comments lines in and out.

Completions may come later than asked (a console asks its kernel): they are
shown when they come, each with what it is, filtered by what is typed since.

The assistant's hints, when the editor is given them (models/hints.py):
after a pause in typing what may follow the cursor shows grey (Tab takes it,
Esc or any other key drops it, an answer to text typed since is never
shown); Ctrl+I opens a field under the line for code asked in words, which
comes as a proposal. A change is looked at in the text hunk by hunk
(show_review: a proposal, a change of its file on disk): the lines that go
red and struck out, those that come green, ✓ and ✗ beside each hunk and for
all over the text; the text takes no typing until every hunk is decided,
then it is the review's text (review_ended).
"""

from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QKeySequence,
    QPainter,
    QStandardItem,
    QStandardItemModel,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QCompleter,
    QPlainTextEdit,
    QTextEdit,
    QToolTip,
    QWidget,
)
from pygments.lexers import PythonLexer
from pygments.token import Comment, Keyword, Name, Number, Operator, String, Token

from thzdaq_gui import theme
from thzdaq_gui.ask_box import AskBox
from thzdaq_gui.assistant.hints import IN_FILE
from thzdaq_gui.models.hints import NO_SERVER, HintsModel, Request
from thzdaq_gui.review import Kind, Review, Row, Source, joined
from thzdaq_gui.review_bar import HunkButtons, ReviewBar

INDENT = "    "
COMMENT = "# "
# Words that complete a word, at the cursor: (text, line from 1, column from 0)
Complete = Callable[[str, int, int], List[str]]
Word = Tuple[str, str]  # a completion: its text, and what it is (may be empty)
WORD = Qt.UserRole  # the text a completion inserts, apart from what it shows

# Colours of tokens: the theme's, in the order pygments' types nest
COLOURS = (
    (Comment, theme.MUTED),
    (String, "#a5d6a7"),
    (Number, "#90caf9"),
    (Keyword, theme.ACCENT),
    (Name.Builtin, "#ce93d8"),
    (Name.Function, "#ffe082"),
    (Name.Class, "#ffe082"),
    (Name.Decorator, "#ce93d8"),
    (Operator.Word, theme.ACCENT),
)
CURRENT_LINE = "#2f2f2f"
PROBLEM_LINE = "#4a2424"
GOES_LINE = "#4b2326"  # a line a waiting hunk takes away
COMES_LINE = "#233f27"  # a line it puts in
ROW_MARKS = {Kind.GOES: ("−", theme.BAD), Kind.COMES: ("+", theme.GOOD)}
GHOST_PAUSE_MS = 600  # typing paused this long asks for a ghost
ASK = QKeySequence("Ctrl+I")
NOTHING_CHANGED = "The assistant changed nothing"
TEXT_CHANGED = "The text changed while the assistant wrote: ask again"


def text_format(colour: str) -> QTextCharFormat:
    found = QTextCharFormat()
    found.setForeground(QColor(colour))
    return found


class PythonHighlighter(QSyntaxHighlighter):
    """Tokens of each line by pygments: a string over lines shows as code past
    its first line, which the editor of a short script can bear."""

    def __init__(self, document):
        super().__init__(document)
        self.lexer = PythonLexer(stripnl=False, ensurenl=False)
        self.formats = [(kind, text_format(colour)) for kind, colour in COLOURS]

    def format_of(self, kind) -> Optional[QTextCharFormat]:
        return next((found for k, found in self.formats if kind in k), None)

    def highlightBlock(self, text: str) -> None:
        at = 0
        for kind, value in self.lexer.get_tokens(text):
            found = None if kind is Token.Text else self.format_of(kind)
            if found is not None:
                self.setFormat(at, len(value), found)
            at += len(value)


class LineNumbers(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.numbers_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_numbers(self, event)


class CodeEditor(QPlainTextEdit):
    saved = Signal()  # Ctrl+S
    review_ended = Signal()  # every hunk decided: the text is the review's

    def __init__(
        self,
        complete: Optional[Complete] = None,
        hints: Optional[HintsModel] = None,
        where: str = IN_FILE,
        parent=None,
    ):
        """hints: the assistant's, for code where the editor is (where: a
        file, a console); None, the editor has none."""
        super().__init__(parent)
        self.complete = complete
        self.hints = hints
        self.where = where
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.highlighter = PythonHighlighter(self.document())
        self.numbers = LineNumbers(self)
        self.problems: Dict[int, str] = {}  # line from 1 -> what is wrong there
        self.completion_start = 0  # where what the completions shown replace begins
        # A change looked at: its rows as shown, ✓ and ✗ of its waiting hunks
        self.review: Optional[Review] = None
        self.rows: List[Row] = []
        self.reviewBar = ReviewBar(self.decide_all, self)
        self.hunkButtons: List[HunkButtons] = []
        self.hunkRows: Dict[int, int] = {}  # the first row of each waiting hunk
        # The ghost: what may follow the cursor, at ghost_at; the question
        # for it after a pause in typing
        self.ghost: Optional[str] = None
        self.ghost_at = -1
        self.asked_ghost: Optional[Request] = None
        self.pause = QTimer(self)
        self.pause.setSingleShot(True)
        self.pause.setInterval(GHOST_PAUSE_MS)
        self.pause.timeout.connect(self.ask_ghost)
        # Ctrl+I: the field and its question
        self.askBox = AskBox(self.viewport())
        self.askBox.asked.connect(self._write)
        self.askBox.closed.connect(self._ask_closed)
        self.asked_code: Optional[Request] = None
        self.blockCountChanged.connect(self._fit_numbers)
        self.updateRequest.connect(self._scroll_numbers)
        self.cursorPositionChanged.connect(self.mark_lines)
        self.cursorPositionChanged.connect(self._cursor_moved)
        self._fit_numbers()
        self.mark_lines()
        self.completer = QCompleter(self)
        self.completer.setModel(QStandardItemModel(self.completer))
        self.completer.setCompletionRole(WORD)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.activated.connect(self.insert_completion)

    # Line numbers, and the bar of a review over the text
    def numbers_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * max(3, digits)

    def _bar_height(self) -> int:
        return self.reviewBar.sizeHint().height() if self.review is not None else 0

    def _fit_numbers(self, *_) -> None:
        self.setViewportMargins(self.numbers_width(), self._bar_height(), 0, 0)
        self._place_parts()

    def _scroll_numbers(self, rect: QRect, dy: int) -> None:
        if dy:
            self.numbers.scroll(0, dy)
            self._place_hunks()
        else:
            self.numbers.update(0, rect.y(), self.numbers.width(), rect.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_parts()

    def _place_parts(self) -> None:
        area = self.contentsRect()
        top = self._bar_height()
        self.numbers.setGeometry(
            QRect(
                area.left(), area.top() + top, self.numbers_width(), area.height() - top
            )
        )
        self.reviewBar.setGeometry(QRect(area.left(), area.top(), area.width(), top))
        self._place_hunks()

    def paint_numbers(self, widget: QWidget, event) -> None:
        painter = QPainter(widget)
        painter.fillRect(event.rect(), QColor(theme.BASE))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                text, colour = self._number(number)
                painter.setPen(QColor(colour))
                painter.drawText(
                    0, top, widget.width() - 6, height, Qt.AlignRight, text
                )
            block = block.next()
            top += round(self.blockBoundingRect(block).height())
            number += 1

    def _number(self, block: int) -> Tuple[str, str]:
        """What the gutter shows at a block (from 0), and its colour: the line,
        or for a hunk's rows not in the text − or +."""
        if self.review is None or block >= len(self.rows):
            line = block + 1
            return str(line), theme.BAD if line in self.problems else theme.MUTED
        row = self.rows[block]
        mark, colour = ROW_MARKS.get(row.kind, ("", theme.MUTED))
        return (mark if row.line is None else str(row.line)), colour

    # Lines marked: the rows of a review, the one with the cursor, those a
    # check found wrong
    def mark_lines(self) -> None:
        marks: List[QTextEdit.ExtraSelection] = []
        if self.review is not None:
            for number, row in enumerate(self.rows):
                if row.kind is not Kind.SAME:
                    block = self.document().findBlockByNumber(number)
                    marks.extend(self._row_marks(QTextCursor(block), row.kind))
        else:
            for line in self.problems:
                block = self.document().findBlockByNumber(line - 1)
                if block.isValid():
                    marks.append(self._mark(QTextCursor(block), PROBLEM_LINE))
            marks.append(self._mark(self.textCursor(), CURRENT_LINE))
        self.setExtraSelections(marks)

    @staticmethod
    def _mark(cursor: QTextCursor, colour: str) -> QTextEdit.ExtraSelection:
        mark = QTextEdit.ExtraSelection()
        mark.format.setBackground(QColor(colour))
        mark.format.setProperty(QTextFormat.FullWidthSelection, True)
        mark.cursor = cursor
        mark.cursor.clearSelection()
        return mark

    def _row_marks(
        self, cursor: QTextCursor, kind: Kind
    ) -> List[QTextEdit.ExtraSelection]:
        """A hunk's row: its line, struck out when it goes."""
        mark = self._mark(cursor, GOES_LINE if kind is Kind.GOES else COMES_LINE)
        if kind is Kind.GOES:
            struck = QTextEdit.ExtraSelection()
            struck.format.setFontStrikeOut(True)
            struck.format.setForeground(QColor(theme.MUTED))
            struck.cursor = QTextCursor(cursor.block())
            struck.cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            return [mark, struck]
        return [mark]

    def set_problems(self, problems: Dict[int, str]) -> None:
        self.problems = dict(problems)
        self.mark_lines()
        self.numbers.update()

    def go_to(self, line: int) -> None:
        """The cursor at the start of a line (from 1), shown."""
        block = self.document().findBlockByNumber(max(0, line - 1))
        self.setTextCursor(QTextCursor(block))
        self.centerCursor()
        self.setFocus()

    def event(self, event) -> bool:
        if event.type() == event.Type.ToolTip and self.review is None:
            line = self.cursorForPosition(event.pos()).blockNumber() + 1
            if line in self.problems:
                QToolTip.showText(event.globalPos(), self.problems[line], self)
                return True
        return super().event(event)

    # A change looked at hunk by hunk
    def code(self) -> str:
        """The text: while a change is looked at, with what is decided of it."""
        return self.toPlainText() if self.review is None else self.review.text()

    def show_review(self, review: Review) -> None:
        """The change in the text, hunk by hunk; one looked at before gives
        way to it (its base is what was decided of that one)."""
        self.dismiss_ghost()
        self.askBox.hide()
        self.review = review
        self.setReadOnly(True)
        self._show_rows()
        first = review.first_row(review.waiting()[0]) if review.waiting() else None
        if first is not None:
            self.setTextCursor(QTextCursor(self.document().findBlockByNumber(first)))
            self.centerCursor()
        if review.done():
            self._end_review()

    def propose(self, base: str, proposed: str) -> Optional[str]:
        """What the assistant wrote for the text base, as a proposal; None
        once shown, else why not (it changes nothing, the text is not base
        any more)."""
        if self.code() != base:
            return TEXT_CHANGED
        review = Review(base, proposed, Source.PROPOSED)
        if review.done():
            return NOTHING_CHANGED
        self.show_review(review)
        return None

    def decide(self, index: int, take: bool) -> None:
        if self.review is None:
            return
        if take:
            self.review.take(index)
        else:
            self.review.leave(index)
        self._decided()

    def decide_all(self, take: bool) -> None:
        if self.review is None:
            return
        if take:
            self.review.take_all()
        else:
            self.review.leave_all()
        self._decided()

    def _decided(self) -> None:
        if self.review.done():
            self._end_review()
            return
        scrolled = self.verticalScrollBar().value()
        self._show_rows()
        self.verticalScrollBar().setValue(scrolled)

    def _show_rows(self) -> None:
        self.rows = self.review.rows()
        self.setPlainText(joined(self.rows))
        self.reviewBar.show_review(self.review)
        for buttons in self.hunkButtons:
            buttons.deleteLater()
        self.hunkButtons = [
            HunkButtons(self.review, index, self.decide, self.viewport())
            for index in self.review.waiting()
        ]
        self.hunkRows = {
            b.index: self.review.first_row(b.index) for b in self.hunkButtons
        }
        for buttons in self.hunkButtons:
            buttons.show()
        self._fit_numbers()
        self.mark_lines()

    def _end_review(self) -> None:
        text = self.review.text()
        line = self.textCursor().blockNumber() + 1
        self.set_text(text)
        self.go_to(min(line, self.blockCount()))
        self.review_ended.emit()

    def set_text(self, text: str) -> None:
        """The text replaced; a change looked at is given up."""
        self.review = None
        self.rows = []
        for buttons in self.hunkButtons:
            buttons.deleteLater()
        self.hunkButtons = []
        self.reviewBar.hide()
        self.setReadOnly(False)
        self.setPlainText(text)
        self._fit_numbers()
        self.mark_lines()

    def _place_hunks(self) -> None:
        """✓ and ✗ of each waiting hunk at the right of its first row."""
        if self.review is None:
            return
        width = self.viewport().width()
        for buttons in self.hunkButtons:
            block = self.document().findBlockByNumber(self.hunkRows[buttons.index])
            top = (
                self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
            )
            size = buttons.sizeHint()
            buttons.setGeometry(
                width - size.width() - 4, round(top), size.width(), size.height()
            )

    # The ghost
    def hints_on(self) -> bool:
        return self.hints is not None and self.hints.available()

    def ask_ghost(self) -> None:
        """What may follow the cursor, asked of the assistant: on a line with
        nothing after the cursor, the text not looked at, nothing selected."""
        cursor = self.textCursor()
        rest = cursor.block().text()[cursor.positionInBlock() :]
        text = self.toPlainText()
        if (
            not self.hints_on()
            or self.isReadOnly()
            or cursor.hasSelection()
            or rest.strip()
            or not text.strip()
            or self.completer.popup().isVisible()
        ):
            return
        self.asked_ghost = self.hints.ghost(self.where, text, cursor.position(), self)
        self.asked_ghost.answered.connect(self._ghost_came)
        self.asked_ghost.failed.connect(self._ghost_failed)

    def _ghost_came(self, text: str) -> None:
        self.asked_ghost = None
        if text:
            self.ghost, self.ghost_at = text, self.textCursor().position()
            self.viewport().update()

    def _ghost_failed(self, _why: str) -> None:
        self.asked_ghost = None  # nothing shows: the next pause asks again

    def dismiss_ghost(self) -> None:
        """The ghost shown and the question for one go."""
        self.pause.stop()
        if self.asked_ghost is not None:
            self.asked_ghost.cancel()
            self.asked_ghost = None
        if self.ghost is not None:
            self.ghost = None
            self.viewport().update()

    def accept_ghost(self) -> None:
        ghost = self.ghost
        self.dismiss_ghost()
        self.textCursor().insertText(ghost)
        self.ensureCursorVisible()

    def _cursor_moved(self) -> None:
        if self.ghost is not None and self.textCursor().position() != self.ghost_at:
            self.dismiss_ghost()

    def focusOutEvent(self, event) -> None:
        if not self.askBox.isVisible():
            self.dismiss_ghost()
        super().focusOutEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.ghost is None:
            return
        painter = QPainter(self.viewport())
        font = self.font()
        font.setItalic(True)
        painter.setFont(font)
        caret = self.cursorRect()
        metrics = self.fontMetrics()
        left = round(self.contentOffset().x() + self.document().documentMargin())
        lines = self.ghost.split("\n")
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(caret.left() + 1, caret.top() + metrics.ascent(), lines[0])
        for number, line in enumerate(lines[1:], 1):
            top = caret.top() + number * metrics.height()
            # Over the lines below: they come back when it goes
            painter.fillRect(
                0, top, self.viewport().width(), metrics.height(), QColor(theme.BASE)
            )
            painter.drawText(left, top + metrics.ascent(), line)

    # Ctrl+I: code asked for in words
    def ask(self) -> None:
        """The field for it under the line of the cursor; without the
        assistant's server, a word of why."""
        if not self.hints_on():
            QToolTip.showText(
                self.mapToGlobal(self.cursorRect().bottomLeft()), NO_SERVER, self
            )
            return
        if self.review is not None:
            return
        self.dismiss_ghost()
        caret = self.cursorRect()
        x = max(0, caret.left() - 4)
        self.askBox.open(x, caret.bottom() + 2, self.viewport().width() - x - 8)

    def _write(self, asked: str) -> None:
        cursor = self.textCursor()
        code = self.toPlainText()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        self.asked_code = self.hints.write(self.where, code, start, end, asked, self)
        self.asked_code.answered.connect(lambda text: self._written(code, text))
        self.asked_code.failed.connect(self._not_written)

    def _written(self, base: str, text: str) -> None:
        self.asked_code = None
        why = self.propose(base, text)
        if why is None:
            self.askBox.hide()
            self.setFocus()
        else:
            self.askBox.tell(why)

    def _not_written(self, why: str) -> None:
        self.asked_code = None
        self.askBox.tell(why)

    def _ask_closed(self) -> None:
        if self.asked_code is not None:
            self.asked_code.cancel()
            self.asked_code = None
        self.setFocus()

    # Keys
    def keyPressEvent(self, event) -> None:
        """While a change is looked at, only moving and copying; Tab takes a
        ghost and Esc drops it; Ctrl+I asks for code; typing asks for a ghost
        after a pause. press() does the rest."""
        if self.review is not None:
            QPlainTextEdit.keyPressEvent(self, event)
            return
        popup = self.completer.popup().isVisible()
        if self.ghost is not None and not popup:
            if event.key() == Qt.Key_Tab and not event.modifiers():
                self.accept_ghost()
                return
            if event.key() == Qt.Key_Escape:
                self.dismiss_ghost()
                return
        if QKeySequence(event.keyCombination()) == ASK:
            self.ask()
            return
        revision = self.document().revision()
        self.dismiss_ghost()
        self.press(event)
        if self.document().revision() != revision and event.text() and self.hints_on():
            self.pause.start()

    def press(self, event) -> None:
        """A key the editor of a file takes; a console's input takes some
        otherwise."""
        if self.completer.popup().isVisible() and event.key() in (
            Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Escape,
        ):  # fmt: skip
            event.ignore()  # the popup takes them
            return
        if event.matches(QKeySequence.Save):
            self.saved.emit()
            return
        key, modifiers = event.key(), event.modifiers()
        if key == Qt.Key_Space and modifiers & Qt.ControlModifier:
            self.ask_completions()
            return
        if key == Qt.Key_Slash and modifiers & Qt.ControlModifier:
            self.toggle_comments()
            return
        if key == Qt.Key_Tab:
            self.indent()
            return
        if key == Qt.Key_Backtab:
            self.dedent()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.new_line()
            return
        super().keyPressEvent(event)
        if event.text() == ".":
            self.ask_completions()
        elif self.completer.popup().isVisible():
            self._filter()

    def _lines(self) -> Iterable[QTextCursor]:
        """A cursor at the start of each line of the selection (or the line)."""
        cursor = self.textCursor()
        document = self.document()
        first = document.findBlock(cursor.selectionStart())
        last = document.findBlock(
            max(cursor.selectionStart(), cursor.selectionEnd() - 1)
        )
        block = first
        while block.isValid():
            yield QTextCursor(block)
            if block == last:
                break
            block = block.next()

    def indent(self) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            column = cursor.positionInBlock()
            cursor.insertText(" " * (len(INDENT) - column % len(INDENT)))
            return
        cursor.beginEditBlock()
        for line in self._lines():
            line.insertText(INDENT)
        cursor.endEditBlock()

    def dedent(self) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for line in self._lines():
            text = line.block().text()
            spaces = len(text) - len(text.lstrip(" "))
            for _ in range(min(spaces, len(INDENT))):
                line.deleteChar()
        cursor.endEditBlock()

    def new_line(self) -> None:
        cursor = self.textCursor()
        before = cursor.block().text()[: cursor.positionInBlock()]
        indent = before[: len(before) - len(before.lstrip(" "))]
        if before.rstrip().endswith(":"):
            indent += INDENT
        cursor.insertText("\n" + indent)
        self.ensureCursorVisible()

    def toggle_comments(self) -> None:
        lines = list(self._lines())
        commented = all(
            line.block().text().lstrip().startswith(COMMENT.strip())
            for line in lines
            if line.block().text().strip()
        )
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for line in lines:
            text = line.block().text()
            if not text.strip():
                continue
            at = len(text) - len(text.lstrip())
            line.movePosition(QTextCursor.Right, n=at)
            if commented:
                mark = COMMENT if text[at:].startswith(COMMENT) else COMMENT.strip()
                for _ in mark:
                    line.deleteChar()
            else:
                line.insertText(COMMENT)
        cursor.endEditBlock()

    # Completions
    def word(self) -> str:
        """The part of a name before the cursor."""
        cursor = self.textCursor()
        before = cursor.block().text()[: cursor.positionInBlock()]
        start = len(before)
        while start and (before[start - 1].isalnum() or before[start - 1] == "_"):
            start -= 1
        return before[start:]

    def ask_completions(self) -> None:
        cursor = self.textCursor()
        self.request_completions(
            self.toPlainText(), cursor.blockNumber() + 1, cursor.positionInBlock()
        )

    def request_completions(self, text: str, line: int, column: int) -> None:
        """Ask for the words that complete the one at the cursor; they are
        shown by show_completions. The editor of a file asks complete."""
        if self.complete is not None:
            self.show_completions([(w, "") for w in self.complete(text, line, column)])

    def show_completions(
        self, words: Sequence[Word], start: Optional[int] = None
    ) -> None:
        """start: where what they replace begins in the text (the word at the
        cursor by default)."""
        if start is None:
            start = self.textCursor().position() - len(self.word())
        self.completion_start = start
        model = QStandardItemModel(self.completer)
        for text, kind in words:
            item = QStandardItem(f"{text}    {kind}" if kind else text)
            item.setData(text, WORD)
            model.appendRow(item)
        self.completer.setModel(model)
        if words:
            self._filter()
        else:
            self.completer.popup().hide()

    def typed(self) -> Optional[str]:
        """What the completions shown replace, as typed by now; None once the
        cursor left it."""
        cursor = self.textCursor().position()
        if cursor < self.completion_start:
            return None
        return self.toPlainText()[self.completion_start : cursor]

    def _filter(self) -> None:
        typed = self.typed()
        if typed is None:
            self.completer.popup().hide()
            return
        self.completer.setCompletionPrefix(typed)
        if self.completer.completionCount() == 0:
            self.completer.popup().hide()
            return
        rect = self.cursorRect()
        rect.setWidth(
            self.completer.popup().sizeHintForColumn(0)
            + self.completer.popup().verticalScrollBar().sizeHint().width()
        )
        self.completer.popup().setCurrentIndex(
            self.completer.completionModel().index(0, 0)
        )
        self.completer.complete(rect)

    def insert_completion(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self.completion_start, QTextCursor.KeepAnchor)
        cursor.insertText(text)
        self.setTextCursor(cursor)
