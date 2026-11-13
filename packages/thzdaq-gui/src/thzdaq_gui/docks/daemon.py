"""The daemon in the window: an indicator in the status bar, a banner while it
does not answer, and the Daemon dock with what it is and holds (its status, a
couple of seconds old), the controls a person needs when it misbehaves and
what agents may do.

All of them show a DaemonModel and call its methods.
"""

from typing import Dict

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api.daemon import StopMode
from thzdaq_api.errors import LabError
from thzdaq_api.operation import Rights
from thzdaq_api.rights import FIXED, MEANS, Decision

from thzdaq_gui import theme
from thzdaq_gui.collapsible import Collapsible
from thzdaq_gui.models.daemon import CONNECTING, LOST, OK, PROBLEMS, DaemonModel

COLORS = {
    OK: theme.GOOD,
    PROBLEMS: theme.ACCENT,
    LOST: theme.BAD,
    CONNECTING: theme.MUTED,
}
STATES = {
    OK: "works",
    PROBLEMS: "works, with problems",
    LOST: "does not answer",
    CONNECTING: "connecting…",
}
# How a stop or a restart treats running measurements
MODES = (
    (StopMode.GRACEFUL, "Only when no measurement runs"),
    (StopMode.CANCEL, "End the measurements (they restore, then the safe state)"),
    (StopMode.ABORT, "End them and break the reads that hang"),
)
# What the daemon asks a person whatever agents may do
ALWAYS_ASKED = (
    "Agents never change the profile or answer for a person. A dangerous step "
    "is always asked, and a set agents may do alone is still asked for a jump "
    "×10, a value beyond warn min..max or another measurement's sweep. People "
    "(this window, a terminal) are not limited."
)


def name_of(model: DaemonModel) -> str:
    return "Simulator daemon" if model.session.simulate else "Daemon"


def summary(model: DaemonModel) -> str:
    """For a tooltip: who it is and what it holds."""
    status = model.status
    lines = [f"{name_of(model)} {STATES[model.state]}"]
    if model.state == LOST:
        lines.append(model.why)
    elif status is not None:
        process = status.process
        lines += [
            f"ThzDAQ {process.app_version}, pid {process.pid}, since {process.started}",
            f"{len(status.clients)} client(s), {len(status.runs)} measurement(s)",
            *status.problems,
        ]
    return "\n".join(line for line in lines if line)


class DaemonIndicator(QToolButton):
    """A dot in the status bar: green it works, orange with problems, red it
    does not answer; a click opens the Daemon dock."""

    def __init__(self, model: DaemonModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        model.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        model = self.model
        self.setIcon(theme.icon("circle", COLORS[model.state]))
        self.setText(name_of(model))
        self.setToolTip(summary(model))


class LostBanner(QFrame):
    """Over the docks while the daemon does not answer (the window shows it
    then): why, and starting it."""

    daemon_requested = Signal()  # show the Daemon dock

    def __init__(self, model: DaemonModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setObjectName("lostBanner")
        self.setStyleSheet(
            f"#lostBanner {{ background: {theme.BAD}; }} #lostBanner QLabel "
            "{ color: #111111; }"
        )
        row = QHBoxLayout(self)
        self.text = QLabel()
        self.text.setWordWrap(True)
        start = QPushButton(theme.icon("play"), "Start daemon")
        start.clicked.connect(lambda: start_daemon(self, model))
        more = QPushButton("Daemon…")
        more.clicked.connect(self.daemon_requested)
        row.addWidget(self.text, 1)
        row.addWidget(start)
        row.addWidget(more)
        model.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.text.setText(f"No connection to the daemon: {self.model.why}")


def start_daemon(parent: QWidget, model: DaemonModel) -> None:
    try:
        model.start()
    except LabError as e:
        QMessageBox.critical(parent, name_of(model), f"{e.message}\n\n{e.hint}".strip())


class DaemonWidget(QWidget):
    """The Daemon dock: its state, its process and what it holds, and controls."""

    def __init__(self, model: DaemonModel, parent=None):
        super().__init__(parent)
        self.model = model
        layout = QVBoxLayout(self)
        self.state = QLabel()
        self.state.setProperty("role", "title")
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setProperty("role", "muted")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "State"])
        self.mode = QComboBox()
        for mode, title in MODES:
            self.mode.addItem(title, mode)
        self.mode.setToolTip("How Restart and Stop treat running measurements")
        self.btnRestart = QPushButton(theme.icon("restart"), "Restart")
        self.btnRestart.clicked.connect(self.restart_daemon)
        self.btnStop = QPushButton(theme.icon("stop"), "Stop")
        self.btnStop.clicked.connect(self.stop_daemon)
        self.btnStart = QPushButton(theme.icon("play"), "Start")
        self.btnStart.clicked.connect(lambda: start_daemon(self, model))
        self.btnKill = QPushButton(theme.icon("skull-outline"), "Kill")
        self.btnKill.setToolTip("End a daemon that does not answer")
        self.btnKill.clicked.connect(self.kill_daemon)
        log = QPushButton(theme.icon("text-box-outline"), "Open log")
        log.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(model.log())))
        )
        controls = QHBoxLayout()
        for widget in (self.btnRestart, self.btnStop, self.btnStart, self.btnKill, log):
            controls.addWidget(widget)
        controls.addStretch()
        self.agents = AgentRights(model)
        layout.addWidget(self.state)
        layout.addWidget(self.details)
        layout.addWidget(self.mode)
        layout.addLayout(controls)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.agents)
        model.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        model, status = self.model, self.model.status
        self.state.setText(f"{name_of(model)} {STATES[model.state]}")
        self.state.setStyleSheet(f"color: {COLORS[model.state]}")
        lost = model.state == LOST
        for button in (self.btnRestart, self.btnStop):
            button.setEnabled(not lost)
        for button in (self.btnStart, self.btnKill):
            button.setEnabled(lost)
        if lost or status is None:
            self.details.setText(model.why)
            return
        process = status.process
        self.details.setText(
            f"ThzDAQ {process.app_version} · pid {process.pid} · port {process.port} · "
            f"since {process.started}"
            + (f" · {process.usage()}" if process.usage() else "")
            + f"<br>Profile: {status.path or 'none'}"
        )
        self.tree.clear()
        sections = (
            ("Problems", [(problem, "") for problem in status.problems]),
            ("Errors", [(error, "") for error in reversed(process.errors)]),
            ("Clients", [
                (f"{c.kind} {c.origin}", f"pid {c.pid}, since {c.since}")
                for c in status.clients
            ]),
            ("Measurements", [
                (f"#{r.id} {r.title}", f"{r.done}/{r.total or '?'} · {r.origin}")
                for r in status.runs
            ]),
            ("Scripts", [
                (f"{s.id} {s.name}", f"pid {s.pid} · since {s.started} · {s.log}")
                for s in status.scripts
            ]),
            ("Queues", [
                (lane.instrument, lane_state(lane)) for lane in status.lanes
            ]),
            ("Connections", [
                (c.label, ("broken" if c.broken else "open" if c.open else "closed")
                 + f" · {', '.join(c.instruments)}")
                for c in status.connections
            ]),
            ("Polls", [
                (p.ref, f"every {p.interval:g} s, {p.subscribers} subscriber(s)")
                for p in status.polls
            ]),
        )  # fmt: skip
        for title, rows in sections:
            section = QTreeWidgetItem([f"{title} ({len(rows)})", ""])
            for name, state in rows:
                section.addChild(QTreeWidgetItem([name, state]))
            self.tree.addTopLevelItem(section)
            section.setExpanded(bool(rows))
        self.tree.resizeColumnToContents(0)

    def chosen_mode(self) -> StopMode:
        return self.mode.currentData()

    # Not stop(): the window calls a dock's stop() to end its work when it closes
    def restart_daemon(self) -> None:
        if self.asked("Restart the daemon?"):
            self.model.restart(self.chosen_mode())

    def stop_daemon(self) -> None:
        if self.asked("Stop the daemon? The window loses its connection."):
            self.model.stop(self.chosen_mode())

    def kill_daemon(self) -> None:
        if self.asked("Kill the daemon? Measurements it runs end as interrupted."):
            killed = self.model.kill()
            QMessageBox.information(
                self,
                name_of(self.model),
                f"Ended pid {killed}" if killed else "No daemon ran",
            )

    def asked(self, question: str) -> bool:
        answer = QMessageBox.question(self, name_of(self.model), question)
        return answer == QMessageBox.Yes


def lane_state(lane) -> str:
    """How an instrument's queue stands: what waits, what runs and how long."""
    text = f"{lane.pending} waiting"
    if lane.current:
        text += f" · {lane.current} for {lane.busy_for:.0f} s"
    return text + (" · STUCK" if lane.stuck else "")


class AgentRights(Collapsible):
    """What agents may do, by the rights a call needs: allow, ask or deny,
    chosen here and kept by the daemon; the fixed ones are shown, not chosen."""

    def __init__(self, model: DaemonModel, parent=None):
        super().__init__("Agents may", "daemon/agents", expanded=False, parent=parent)
        self.model = model
        table = QWidget()
        grid = QGridLayout(table)
        grid.setContentsMargins(0, 0, 0, 0)
        self.choices: Dict[Rights, QComboBox] = {}
        for row, rights in enumerate(Rights):
            choice = QComboBox()
            for decision in Decision:
                choice.addItem(decision.value, decision)
            choice.setEnabled(rights not in FIXED)
            choice.activated.connect(
                lambda _, r=rights, c=choice: self.choose(r, c.currentData())
            )
            means = QLabel(MEANS[rights])
            means.setProperty("role", "muted")
            means.setWordWrap(True)
            title = rights.value.replace("_", " ").capitalize()  # Raw query
            grid.addWidget(QLabel(title), row, 0)
            grid.addWidget(choice, row, 1)
            grid.addWidget(means, row, 2)
            self.choices[rights] = choice
        grid.setColumnStretch(2, 1)
        self.addWidget(table)
        rules = QLabel(ALWAYS_ASKED)
        rules.setWordWrap(True)
        rules.setProperty("role", "muted")
        self.addWidget(rules)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.ACCENT}")
        self.status.hide()
        self.addWidget(self.status)
        model.changed.connect(self.refresh)
        model.refused.connect(self.refused)
        self.refresh()

    def refresh(self) -> None:
        settings = self.model.settings
        if settings is None:
            return
        for rights, choice in self.choices.items():
            choice.setCurrentIndex(choice.findData(settings.agents[rights]))
        allowed = [r.value for r, d in settings.agents.items() if d == Decision.ALLOW]
        self.set_summary(f"alone: {', '.join(allowed) or 'nothing'}")

    def choose(self, rights: Rights, decision: Decision) -> None:
        self.status.hide()
        self.model.let_agents(rights, decision)

    def refused(self, why: str) -> None:
        self.status.setText(why)
        self.status.show()
