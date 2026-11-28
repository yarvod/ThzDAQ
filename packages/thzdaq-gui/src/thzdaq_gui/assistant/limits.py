"""Codex's usage limits (its 5-hour and weekly windows) as Codex itself keeps
them. codex-acp (2.7.0) knows them (account/rateLimits of Codex's app-server)
but tells them only in the words of its /status command, never as data over
ACP. Codex writes each snapshot it gets into the log of the session it came
with, after each of the model's answers:

    <CODEX_HOME, else ~/.codex>/sessions/YYYY/MM/DD/rollout-<time>-<session>.jsonl
    {"timestamp": ..., "type": "event_msg", "payload": {"type": "token_count",
     "rate_limits": {"primary": {"used_percent", "window_minutes",
     "resets_at"}, "secondary": {...}}}}

The last snapshot of a session's log is read here (of the newest logs while
no session is named: the limits are the account's, whatever the session).
Files only, no Qt; read off the GUI thread."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, List, Mapping, Optional, Tuple

from thzdaq_gui.assistant.chat import Limit

HOME = "CODEX_HOME"  # Codex's folder, when not ~/.codex
SESSIONS = "sessions"
SNAPSHOT = "rate_limits"
WINDOWS = ("primary", "secondary")  # the 5-hour window, the weekly one
TAIL_BYTES = 256 * 1024  # the end of a log its last snapshot is looked for in
NEWEST = 20  # logs looked into while no session is named


def home(environment: Mapping[str, str]) -> Path:
    """Codex's folder in the adapter's environment."""
    found = environment.get(HOME)
    return Path(found) if found else Path.home() / ".codex"


def log_of(home: Path, session: str) -> Optional[Path]:
    """The log of a session; None while Codex keeps none."""
    found = sorted((home / SESSIONS).glob(f"*/*/*/rollout-*-{session}.jsonl"))
    return found[-1] if found else None


def newest_logs(home: Path) -> Iterator[Path]:
    """The logs, the newest begun first."""
    for day in sorted((home / SESSIONS).glob("*/*/*"), reverse=True):
        yield from sorted(day.glob("rollout-*.jsonl"), reverse=True)


def latest(home: Path, session: Optional[str] = None) -> Tuple[Limit, ...]:
    """The windows of the last snapshot: of the session's log when it is
    named and kept, else of the newest logs that hold one; none without."""
    if session is not None:
        log = log_of(home, session)
        return limits_of(log) if log is not None else ()
    for count, log in enumerate(newest_logs(home)):
        if count == NEWEST:
            break
        found = limits_of(log)
        if found:
            return found
    return ()


def limits_of(log: Path) -> Tuple[Limit, ...]:
    """The windows of the last snapshot in a log's end; none without one."""
    try:
        with open(log, "rb") as file:
            file.seek(0, 2)
            size = file.tell()
            file.seek(max(0, size - TAIL_BYTES))
            tail = file.read().decode("utf-8", errors="replace")
    except OSError:
        return ()
    for line in reversed(tail.splitlines()):
        if SNAPSHOT not in line:
            continue
        found = _snapshot(line)
        if found:
            return found
    return ()


def _snapshot(line: str) -> Tuple[Limit, ...]:
    try:
        entry = json.loads(line)
    except ValueError:  # the first line of the tail, cut
        return ()
    payload = entry.get("payload") if isinstance(entry, dict) else None
    limits = payload.get(SNAPSHOT) if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return ()
    told = _time(entry.get("timestamp"))
    windows: List[Limit] = []
    for name in WINDOWS:
        window = _window(limits.get(name), told)
        if window is not None:
            windows.append(window)
    return tuple(windows)


def _window(window: Any, told: float) -> Optional[Limit]:
    """A window as Codex writes it: when it starts anew as a moment
    (resets_at) or, by older Codex, in seconds from the snapshot."""
    if not isinstance(window, dict):
        return None
    try:
        minutes = int(window["window_minutes"])
        used = float(window["used_percent"])
    except (KeyError, TypeError, ValueError):
        return None
    resets: Optional[float] = None
    if isinstance(window.get("resets_at"), (int, float)):
        resets = float(window["resets_at"])
    elif isinstance(window.get("resets_in_seconds"), (int, float)):
        resets = told + float(window["resets_in_seconds"])
    return Limit(minutes, used, resets, told)


def _time(stamp: Any) -> float:
    """An ISO 8601 moment as seconds since the epoch; 0 when it does not read."""
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
