"""The chat's bar under the input, a view of the mode AssistantModel shows:
the model that answers and how hard it thinks (ModelPicker: a compact button,
a popup of the models with a line each, the chosen one checked, its reasoning
efforts in a row under them); what the agent may do without asking
(PolicyPicker: Codex's modes, full access confirmed first; hidden for a chat
that never acts on its own); how much of the agent's usage limits is left
(LimitsLabel: Codex's 5-hour and weekly windows in a few letters, hidden for
a chat whose agent tells none); and how much of the context the chat fills
(UsageRing: a ring, hovered or clicked, a card of the tokens and the limits,
UsageView)."""

import time
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.assistant.chat import Choice, Limit
from thzdaq_gui.chat_widgets import (
    ContextRing,
    ElidedLabel,
    PickerButton,
    Popup,
    Row,
    Segments,
    grouped,
)
from thzdaq_gui.models.assistant import AssistantModel, Tokens, share

NO_MODEL = "No model"
LOADING = "Loading models…"
EFFORT = "Effort"
CHANGE_MODE = "Change the mode"  # the title of a mode's confirmation
UNKNOWN = "—"  # tokens the model's server or the agent did not tell
MODEL_ROOM = 90  # pixels of the model's name kept as the bar narrows
SUMMED = (
    "In and out are summed over the model's requests: each reads the whole"
    " chat again, so in grows faster than the context."
)
LIMITS = "Limits"  # of the agent's usage, in the card
LOW = 20.0  # percent left of a window shown in the accent colour
HOUR, DAY = 60, 24 * 60  # minutes
WINDOWS = {5 * HOUR: "5 hours", 7 * DAY: "Week"}  # Codex's, by their length


class ChoicesPopup(Popup):
    """Choices in a list (Row), the one chosen checked; picked tells the one
    picked, and the popup closes."""

    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(4, 4, 4, 4)
        self.column.setSpacing(2)
        self.list = QVBoxLayout()
        self.list.setSpacing(0)
        self.column.addLayout(self.list)
        self.rows: Dict[str, Row] = {}

    def show_choices(self, choices: Sequence[Choice], chosen: Optional[str]) -> None:
        """The same choices keep their rows, the chosen one checked anew."""
        listed = [(row.text(), row.tip) for row in self.rows.values()]
        if list(self.rows) == [each.id for each in choices] and listed == [
            (each.title, each.tip) for each in choices
        ]:
            for id, row in self.rows.items():
                row.setChecked(id == chosen)
            return
        for row in self.rows.values():
            row.deleteLater()
        self.rows = {}
        for each in choices:
            row = Row(each.title, each.tip)
            row.setChecked(each.id == chosen)
            row.clicked.connect(lambda _=False, id=each.id: self._pick(id))
            self.rows[each.id] = row
            self.list.addWidget(row)
        if self.isVisible():
            self.adjustSize()

    def _pick(self, id: str) -> None:
        self.hide()
        self.picked.emit(id)


class ModelPopup(ChoicesPopup):
    """The models, then that the real ones are being found (while the list
    is what was known last, or none), then the chosen one's efforts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loading = ElidedLabel(LOADING)
        self.loading.set_color(theme.MUTED)
        self.effortLabel = QLabel(EFFORT)
        self.effortLabel.setStyleSheet(f"color: {theme.MUTED};")
        self.efforts = Segments()
        self.column.addWidget(self.loading)
        self.column.addWidget(self.effortLabel)
        self.column.addWidget(self.efforts, 0, Qt.AlignLeft)

    def show_efforts(self, efforts: Sequence[Choice], chosen: Optional[str]) -> None:
        self.efforts.show_choices(efforts, chosen)
        self.effortLabel.setVisible(bool(efforts))
        self.efforts.setVisible(bool(efforts))


def named(choices: Sequence[Choice], id: Optional[str]) -> Optional[Choice]:
    return next((each for each in choices if each.id == id), None)


class ModelPicker(PickerButton):
    """The model and its effort ("GPT-5 · High"); "Loading models…" while
    they are found; a click, the models and efforts (ModelPopup)."""

    def __init__(self, model: AssistantModel, parent=None):
        super().__init__(
            theme.icon("chevron-down", theme.MUTED), after=True, least=MODEL_ROOM,
            parent=parent,
        )  # fmt: skip
        self.model = model
        self.popup = ModelPopup(self)
        self.popup.picked.connect(model.choose_model)
        self.popup.efforts.chosen.connect(model.choose_effort)
        self.clicked.connect(lambda: self.popup.pop(self))

    def show_models(self) -> None:
        model = self.model
        models, efforts = model.models(), model.efforts()
        chosen = named(models, model.chosen_model())
        effort = named(efforts, model.chosen_effort())
        finding = model.finding_models()
        if chosen is not None:
            shown = chosen.title + (f" · {effort.title}" if effort is not None else "")
            self.show_text(shown, chosen.tip)
        else:
            self.show_text(LOADING if finding else NO_MODEL)
        self.popup.show_choices(models, model.chosen_model())
        self.popup.show_efforts(efforts, model.chosen_effort())
        self.popup.loading.setVisible(finding)


class PolicyPicker(PickerButton):
    """What the agent may do without asking, by its name; a click, the
    others with what each allows (a risky one, confirmed first). Hidden when
    the chat offers none."""

    def __init__(self, model: AssistantModel, parent=None):
        super().__init__(theme.icon("shield-check-outline", theme.MUTED), parent=parent)
        self.model = model
        self.popup = ChoicesPopup(self)
        self.popup.picked.connect(self.pick)
        self.clicked.connect(lambda: self.popup.pop(self))

    def show_policies(self) -> None:
        policies = self.model.policies()
        chosen = named(policies, self.model.chosen_policy())
        self.setVisible(bool(policies))
        risky = chosen is not None and bool(chosen.confirm)
        self.setIcon(
            theme.icon("shield-alert-outline", theme.BAD)
            if risky
            else theme.icon("shield-check-outline", theme.MUTED)
        )
        if chosen is not None:
            self.show_text(chosen.title, chosen.tip)
        else:  # none of those offered: the icon alone
            self.show_text("")
        self.popup.show_choices(policies, self.model.chosen_policy())

    def pick(self, id: str) -> None:
        """A policy that asks first is chosen once the person agrees."""
        chosen = named(self.model.policies(), id)
        if chosen is None:
            return
        if chosen.confirm:
            agreed = QMessageBox.question(
                self, CHANGE_MODE, chosen.confirm, QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )  # fmt: skip
            if agreed != QMessageBox.Yes:
                return
        self.model.choose_policy(id)


def context_text(used: int, limit: Optional[int]) -> str:
    """ "27 500 / 258 400 · 11%", or the used ones alone while the limit is not
    known."""
    if not limit:
        return f"{grouped(used)} · limit not known"
    return f"{grouped(used)} / {grouped(limit)} · {round(100 * share(used, limit))}%"


def window_name(minutes: int) -> str:
    """ "5 hours", "Week"; another window by its length."""
    if minutes in WINDOWS:
        return WINDOWS[minutes]
    if minutes % DAY == 0:
        return f"{minutes // DAY} days"
    return f"{minutes / HOUR:g} hours"


def short_name(minutes: int) -> str:
    """ "5h", "7d": a window in a few letters."""
    if minutes % DAY == 0:
        return f"{minutes // DAY}d"
    return f"{minutes / HOUR:g}h"


def moment(when: float, now: float) -> str:
    """ "14:30" today, "3 Dec 14:30" on another day."""
    at, today = datetime.fromtimestamp(when), datetime.fromtimestamp(now)
    shown = at.strftime("%H:%M")
    return shown if at.date() == today.date() else f"{at.day} {at:%b} {shown}"


def left_text(limit: Limit, now: float) -> str:
    """ "86% left" (all of it once the window started anew)."""
    return f"{round(limit.left(now))}% left"


def resets_text(limit: Limit, now: float) -> str:
    """ "resets 14:30"; "" when not told or past."""
    if limit.resets is None or limit.resets <= now:
        return ""
    return f"resets {moment(limit.resets, now)}"


def limits_line(limits: Sequence[Limit], now: float) -> str:
    """ "5h 86% · 7d 88%": what is left of each window, in a few letters."""
    return " · ".join(
        f"{short_name(limit.minutes)} {round(limit.left(now))}%" for limit in limits
    )


def limits_tip(limits: Sequence[Limit], now: float) -> str:
    """Each window in words, and when the agent told them."""
    lines = [
        f"{window_name(limit.minutes)}: {left_text(limit, now)}"
        + (f", {resets_text(limit, now)}" if resets_text(limit, now) else "")
        for limit in limits
    ]
    told = max(limit.told for limit in limits)
    if told:
        lines.append(f"As Codex told them at {moment(told, now)}")
    return "\n".join(lines)


class UsageView(QWidget):
    """The tokens as told: how much of the context the chat fills; in (of it
    cached) and out (of it reasoning) of the last answer and of the chat;
    — where nothing was told. Under them, how much of the agent's usage
    limits is left, when it tells them."""

    ROWS = ("This answer", "This chat")
    COLUMNS = ("In", "Cached", "Out", "Reasoning")

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        grid.addWidget(self._label("Context", theme.MUTED), 0, 0)
        self.context = self._label("", theme.TEXT)
        grid.addWidget(self.context, 0, 1, 1, len(self.COLUMNS), Qt.AlignRight)
        for column, title in enumerate(self.COLUMNS, 1):
            grid.addWidget(self._label(title, theme.MUTED), 1, column, Qt.AlignRight)
        self.cells: Dict[tuple, QLabel] = {}
        for row, title in enumerate(self.ROWS, 2):
            grid.addWidget(self._label(title, theme.MUTED), row, 0)
            for column in range(1, len(self.COLUMNS) + 1):
                self.cells[row, column] = self._label("", theme.TEXT)
                grid.addWidget(self.cells[row, column], row, column, Qt.AlignRight)
        summed = self._label(SUMMED, theme.MUTED)
        summed.setWordWrap(True)
        grid.addWidget(summed, len(self.ROWS) + 2, 0, 1, len(self.COLUMNS) + 1)
        # The agent's limits: a title, then a row per window (name, left, resets)
        self.limits = QWidget()
        self.limitsGrid = QGridLayout(self.limits)
        self.limitsGrid.setContentsMargins(0, 6, 0, 0)
        self.limitsGrid.setHorizontalSpacing(14)
        self.limitsGrid.setVerticalSpacing(4)
        self.limitsGrid.addWidget(self._label(LIMITS, theme.MUTED), 0, 0)
        self.limitRows: List[List[QLabel]] = []
        grid.addWidget(self.limits, len(self.ROWS) + 3, 0, 1, len(self.COLUMNS) + 1)
        self.limits.hide()
        self.setMaximumWidth(380)

    @staticmethod
    def _label(text: str, color: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color: {color};")
        return label

    def show_usage(
        self, context: int, limit: Optional[int], last: Tokens, chat: Tokens
    ) -> None:
        self.context.setText(context_text(context, limit))
        for row, used in enumerate((last, chat), 2):
            told = (
                [
                    grouped(used.read),
                    UNKNOWN if used.cached is None else grouped(used.cached),
                    grouped(used.written),
                    grouped(used.reasoning),
                ]
                if used.known()
                else [UNKNOWN] * len(self.COLUMNS)
            )
            for column, text in enumerate(told, 1):
                self.cells[row, column].setText(text)

    def show_limits(self, limits: Sequence[Limit], now: float) -> None:
        """A row per window, the same rows kept; none: hidden."""
        while len(self.limitRows) < len(limits):
            row = [self._label("", theme.MUTED), self._label("", theme.TEXT)]
            row.append(self._label("", theme.MUTED))
            for column, label in enumerate(row):
                self.limitsGrid.addWidget(
                    label, len(self.limitRows) + 1, column,
                    Qt.AlignRight if column else Qt.AlignLeft,
                )  # fmt: skip
            self.limitRows.append(row)
        for index, row in enumerate(self.limitRows):
            shown = index < len(limits)
            for label in row:
                label.setVisible(shown)
            if shown:
                limit = limits[index]
                row[0].setText(window_name(limit.minutes))
                row[1].setText(left_text(limit, now))
                low = limit.left(now) < LOW
                row[1].setStyleSheet(f"color: {theme.ACCENT if low else theme.TEXT};")
                row[2].setText(resets_text(limit, now))
        self.limits.setVisible(bool(limits))

    def told_limits(self) -> List[List[str]]:
        """As shown: each window's name, what is left, when it resets."""
        if not self.limits.isVisibleTo(self):
            return []
        return [
            [label.text() for label in row]
            for row in self.limitRows
            if row[0].isVisibleTo(self)
        ]

    def told(self) -> List[List[str]]:
        """As shown: the context, then each row's title and numbers."""
        rows = [["Context", self.context.text()]]
        for row, title in enumerate(self.ROWS, 2):
            rows.append(
                [title]
                + [
                    self.cells[row, column].text()
                    for column in range(1, len(self.COLUMNS) + 1)
                ]
            )
        return rows


class UsageRing(ContextRing):
    """The ring by the input, filled with the share of the context the chat
    fills; hovered or clicked, its card of the tokens (UsageView)."""

    def __init__(self, model: AssistantModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.card = Popup(self)
        self.view = UsageView()
        holder = QVBoxLayout(self.card)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(self.view)
        self.hovered.connect(self._hovered)
        self.clicked.connect(self._clicked)

    def show_usage(self) -> None:
        model = self.model
        self.show_share(model.context_share())
        told = context_text(model.usage.context, model.context_limit())
        self.setAccessibleName(f"Context {told}")
        if self.card.isVisible():
            self._show_tokens()
            self.card.adjustSize()

    def _show_tokens(self) -> None:
        model = self.model
        self.view.show_usage(
            model.usage.context, model.context_limit(), model.last_usage, model.usage
        )
        self.view.show_limits(model.limits(), time.time())

    def _hovered(self, on: bool) -> None:
        if on:
            self._show_tokens()
            self.card.hover(self)
        else:
            self.card.unhover()

    def _clicked(self) -> None:
        """Shown as it was hovered, it is popped: it stays as the pointer
        leaves, until a click elsewhere."""
        self._show_tokens()
        self.card.pop(self)


class LimitsLabel(ElidedLabel):
    """What is left of the agent's usage limits, by the ring: "5h 86% · 7d
    88%", in the accent colour when a window runs low, each in words with
    when it resets as its tip; cut as the bar narrows, never widening the
    dock. Hidden for a chat whose agent tells none."""

    def __init__(self, model: AssistantModel, parent=None):
        super().__init__(parent=parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.model = model
        model.usage_changed.connect(self.show_limits)
        model.mode_changed.connect(self.show_limits)
        self.show_limits()

    def show_limits(self) -> None:
        limits, now = self.model.limits(), time.time()
        self.setVisible(bool(limits))
        if not limits:
            return
        low = min(limit.left(now) for limit in limits) < LOW
        self.set_color(theme.ACCENT if low else theme.MUTED)
        self.setText(limits_line(limits, now))
        self.setToolTip(limits_tip(limits, now))  # in place of the text
        self.setAccessibleName(f"Usage limits {self.text()}")
