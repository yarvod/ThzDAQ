"""Python consoles: the kernel's owner on a real ipykernel, the console's
model without widgets, its tab offscreen (keys, history, tracebacks), and
the Console tab of the window with Editor's Run in console."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from thzdaq_api import console, host

from thzdaq_gui.models.console import (
    ENDED,
    IDLE,
    STARTING,
    ConsoleModel,
    History,
    complete_block,
)

pytest.importorskip("ipykernel", reason="a console's kernel runs where ipykernel is")

START_S = 60.0
FAILING = "def broken(x):\n    return 1 / x\n\nbroken(0)\n"


@pytest.fixture(autouse=True)
def apart(monkeypatch, tmp_path):
    """Kernels keep IPython's history here, and find no daemon: their opening
    says so at once (a traceback)."""
    monkeypatch.setattr(host, "user_dir", lambda: tmp_path / "user")
    monkeypatch.setenv(host.DIR_ENV, str(tmp_path / "daemons"))
    monkeypatch.setenv(host.NO_AUTOSTART_ENV, "1")


class Session(QObject):
    """What a console asks of the window's session."""

    def __init__(self, folder: Path):
        super().__init__()
        self.simulate = True
        self.workspace = SimpleNamespace(folder=folder)


class Heard:
    """What a model told, in order."""

    def __init__(self, model: ConsoleModel):
        self.told = []
        for name in ("entered", "printed", "shown", "raised", "told", "completed"):
            getattr(model, name).connect(lambda *a, n=name: self.told.append((n, *a)))

    def of(self, kind):
        return [t[1:] for t in self.told if t[0] == kind]


@pytest.fixture
def started(app, tmp_path, wait):
    """A console's model whose kernel opened; skipped where none starts."""
    made = []

    def make():
        model = ConsoleModel(Session(tmp_path))
        heard = Heard(model)
        made.append(model)
        wait(lambda: model.state != STARTING, START_S)
        if model.state == ENDED:
            pytest.skip(f"no kernel starts here: {heard.of('told')}")
        wait(lambda: heard.of("raised") and model.state == IDLE, START_S)
        return model, heard

    yield make
    for model in made:
        model.stop()
        model.kernel.join(15)


def test_a_block_runs_when_it_is_complete():
    assert complete_block("x = 1") and not complete_block("lab.read(")
    assert not complete_block("for v in values:")
    assert not complete_block("for v in values:\n    print(v)")
    assert complete_block("for v in values:\n    print(v)\n    ")  # a line left blank
    assert complete_block("%run scan.py") and complete_block("x = 1\ny = 2")


def test_history_browses_back_to_what_was_typed():
    history = History()
    history.read(["a = 1", "b = 2"])
    history.add("c = 3")
    assert history.older("typed") == "c = 3"
    assert history.older("") == "b = 2"
    assert history.newer() == "c = 3"
    assert history.newer() == "typed"
    assert history.newer() is None
    history.start_search("draft")
    assert history.find("=") == "c = 3"
    assert history.find("=", older=True) == "b = 2"
    assert history.find("zzz") is None
    assert history.end_search() == "draft"


def test_the_kernel_starts_runs_is_interrupted_restarted_and_stopped(app, wait):
    from thzdaq_gui.kernel import Kernel

    kernel = Kernel(console.kernel_command())
    told = []
    for name in ("started", "failed", "died", "printed", "shown", "raised", "finished"):
        getattr(kernel, name).connect(lambda *a, n=name: told.append((n, *a)))
    kinds = lambda id: [t[0] for t in told if t[1:2] == (id,)]  # noqa: E731
    try:
        kernel.start(dict(os.environ), Path.cwd())
        wait(lambda: told, START_S)
        if told[0][0] == "failed":
            pytest.skip(f"no kernel starts here: {told[0][1]}")
        id = kernel.execute("print('hi'); 6 * 7")
        wait(lambda: "finished" in kinds(id), START_S)
        assert [t for t in told if t[1:2] == (id,)] == [
            ("printed", id, "stdout", "hi\n"),
            ("shown", id, "42"),
            ("finished", id, "ok"),
        ]
        id = kernel.execute("import time\ntime.sleep(60)")
        wait(lambda: kernel.busy, START_S)
        kernel.interrupt()
        wait(lambda: "finished" in kinds(id), 15)
        assert kinds(id) == ["raised", "finished"]
        told.clear()
        kernel.execute("kept = 1")
        kernel.restart(dict(os.environ), Path.cwd())
        wait(lambda: ("started",) in told, START_S)
        id = kernel.execute("kept")  # a new kernel: its names went
        wait(lambda: "finished" in kinds(id), START_S)
        assert kinds(id) == ["raised", "finished"]
        kernel.execute("import os; os._exit(3)")
        wait(lambda: ("died", "exit code 3") in told, START_S)
    finally:
        kernel.stop()
        assert kernel.join(15)


@pytest.mark.parametrize(
    "command",
    [
        [sys.executable, "-c", "raise SystemExit(3)", console.CONNECTION],  # dies
        [str(Path(sys.executable).parent / "no-python"), console.CONNECTION],
    ],
)
def test_a_kernel_that_does_not_start_is_told_and_stops(app, wait, command):
    from thzdaq_gui.kernel import Kernel

    kernel = Kernel(command)
    failed = []
    kernel.failed.connect(failed.append)
    kernel.start(dict(os.environ), Path.cwd())
    wait(lambda: failed, START_S)
    kernel.restart(dict(os.environ), Path.cwd())  # fails again, as cleanly
    wait(lambda: len(failed) == 2, START_S)
    kernel.stop()
    assert kernel.join(15)


def test_a_console_opens_with_the_bench_and_runs_what_waited(started, wait):
    model, heard = started()
    assert heard.of("entered")[0] == (console.OPENING,)
    assert "connect" in "".join(heard.of("raised")[0][0])  # no daemon here
    model.run("print('hi')\n6 * 7")
    wait(lambda: heard.of("shown"), START_S)
    assert heard.of("printed") == [("stdout", "hi\n")] and heard.of("shown") == [
        ("42",)
    ]
    model.restart()
    assert model.state == STARTING
    model.run("x = 5")  # while it starts: after its opening
    wait(lambda: len(heard.of("entered")) == 4, START_S)
    assert heard.of("entered")[2:] == [(console.OPENING,), ("x = 5",)]
    assert model.history.entries[-2:] == ["print('hi')\n6 * 7", "x = 5"]


def test_a_console_completes_from_its_kernel(started, wait):
    model, heard = started()
    model.run("values = [1, 2]")
    wait(lambda: model.state == IDLE)
    model.complete("values.app", len("values.app"))
    wait(lambda: heard.of("completed"), START_S)
    found, start, end = heard.of("completed")[0]
    assert ("append", "function") in [tuple(f) for f in found]
    assert (start, end) == (len("values."), len("values.app"))


def test_inputs_of_every_console_are_kept_between_runs(started, wait):
    first, _ = started()
    first.run("first_input = 1")
    wait(lambda: first.state == IDLE)
    second, _ = started()
    wait(lambda: "first_input = 1" in second.history.entries, START_S)


def type_in(widget, text):
    QTest.keyClicks(widget.input, text)


def test_enter_runs_a_complete_block_else_goes_on(started, wait):
    from thzdaq_gui.docks.console import ConsoleWidget

    model, heard = started()
    widget = ConsoleWidget(model, lambda *place: None)
    type_in(widget, "for v in (1, 2):")
    QTest.keyClick(widget.input, Qt.Key_Return)
    type_in(widget, "print(v)")
    QTest.keyClick(widget.input, Qt.Key_Return)
    assert widget.input.toPlainText() == "for v in (1, 2):\n    print(v)\n    "
    QTest.keyClick(widget.input, Qt.Key_Return)  # on a line left blank: it runs
    wait(lambda: "".join(text for _, text in heard.of("printed")) == "1\n2\n", 15)
    assert widget.input.toPlainText() == ""
    assert ">>> for v in (1, 2):\n...     print(v)" in widget.output.toPlainText()
    type_in(widget, "x = 1")
    QTest.keyClick(widget.input, Qt.Key_Return, Qt.ShiftModifier)  # always a new line
    type_in(widget, "y = 2")
    QTest.keyClick(widget.input, Qt.Key_Return, Qt.ControlModifier)  # always runs
    wait(lambda: model.history.entries[-1] == "x = 1\ny = 2")
    widget.deleteLater()


def test_arrows_and_ctrl_r_bring_earlier_inputs(started, wait):
    from thzdaq_gui.docks.console import ConsoleWidget

    model, _ = started()
    widget = ConsoleWidget(model, lambda *place: None)
    for code in ("a = 1", "b = 2"):
        model.run(code)
    type_in(widget, "draft")
    QTest.keyClick(widget.input, Qt.Key_Up)
    assert widget.input.toPlainText() == "b = 2"
    QTest.keyClick(widget.input, Qt.Key_Up)
    assert widget.input.toPlainText() == "a = 1"
    QTest.keyClick(widget.input, Qt.Key_Down)
    QTest.keyClick(widget.input, Qt.Key_Down)
    assert widget.input.toPlainText() == "draft"
    QTest.keyClick(widget.input, Qt.Key_R, Qt.ControlModifier)
    assert widget.search.isVisibleTo(widget)
    QTest.keyClicks(widget.search, "a =")
    assert widget.input.toPlainText() == "a = 1"
    QTest.keyClick(widget.search, Qt.Key_Escape)  # gone back to what was typed
    assert widget.input.toPlainText() == "draft" and not widget.search.isVisibleTo(
        widget
    )
    widget.deleteLater()


def anchor_point(output):
    """Where the first place of a traceback is shown."""
    from PySide6.QtGui import QTextCursor

    block = output.document().begin()
    while block.isValid():
        found = block.begin()
        while not found.atEnd():
            fragment = found.fragment()
            if fragment.charFormat().isAnchor():
                cursor = QTextCursor(output.document())
                cursor.setPosition(fragment.position() + 1)
                return output.cursorRect(cursor).center()
            found += 1
        block = block.next()
    return None


def test_a_place_of_a_traceback_opens_its_file(started, wait, tmp_path):
    from thzdaq_gui.docks.console import ConsoleWidget

    model, heard = started()
    opened = []
    widget = ConsoleWidget(model, lambda *place: opened.append(place))
    widget.resize(900, 600)
    widget.show()
    widget.output.clear_output()
    file = tmp_path / "broken.py"
    file.write_text(FAILING)
    model.run(console.run_file(file))
    wait(lambda: len(heard.of("raised")) == 2, START_S)
    assert "ZeroDivisionError" in widget.output.toPlainText()
    assert "\x1b" not in widget.output.toPlainText()  # colours, not their codes
    QTest.mouseClick(
        widget.output.viewport(), Qt.LeftButton, pos=anchor_point(widget.output)
    )
    assert opened and opened[0][0].resolve() == file.resolve() and opened[0][1] == 4
    widget.close()
    widget.deleteLater()


def test_the_window_has_a_console_tab_editor_runs_code_in(window, wait, tmp_path):
    from thzdaq_gui.dock_names import CONSOLE

    assert window.docks.state(CONSOLE) != "closed"
    script = tmp_path / "scan.py"
    script.write_text("value = 6 * 7\nprint(value)\n")
    window.code.open(script)
    tab = window.code.widgets[str(script.resolve())]
    tab.editor.go_to(2)
    tab.runSelection.trigger()  # the line of the cursor, in a new console
    (console_tab,) = window.consoles.consoles.values()
    assert window.consoles.tabs.current() is console_tab
    model = console_tab.model
    wait(lambda: model.state != STARTING, START_S)
    if model.state == ENDED:
        pytest.skip("no kernel starts here")
    wait(lambda: "print(value)" in model.history.entries, START_S)
    tab.runFile.trigger()  # in the same console, its names left there
    wait(lambda: "42" in console_tab.output.toPlainText(), START_S)
    assert len(window.consoles.consoles) == 1
    window.consoles.show(f"{CONSOLE}:new")  # Ctrl+K's New console
    assert len(window.consoles.consoles) == 2
    window.consoles.tabs.request_close(console_tab)  # its kernel ends
    assert model.state == ENDED and model.kernel.join(15)
