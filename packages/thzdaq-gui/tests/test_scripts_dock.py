"""The Scripts dock: scripts of the workspace run in the daemon, what they
print as they print it, Stop, templates, folders added to the workspace, and
the script of a measurement from Data."""

import hashlib
import sys

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from thzdaq_api import examples, host
from thzdaq_api.measurement_file import SCRIPT, Measurement
from thzdaq_api.scripts import StartScript
from thzdaq_api.workspace import create

from thzdaq_gui import external_editor
from thzdaq_gui.dock_names import SCRIPTS
from thzdaq_gui.docks.scripts import traceback_place

FAILING = "print('before')\n\n\ndef broken():\n    raise ValueError('no bias')\n\n\nbroken()\n"
SLOW = "import time\nprint('waiting', flush=True)\ntime.sleep(60)\n"


@pytest.fixture
def scripts(window):
    return window.scriptsWidget


@pytest.fixture
def opened(monkeypatch):
    """What VS Code was asked to open."""
    asked = []
    monkeypatch.setattr(external_editor, "code_command", lambda: "code")
    monkeypatch.setattr(host, "start_apart", asked.append)
    return asked


def written(session, name, text):
    folder = session.workspace.scripts
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text)
    session.scripts.refresh_files()
    return path


def file_names(widget):
    return [item.text(0) for item in widget.file_items()]


def run_rows(widget):
    tree = widget.runs
    return [
        (tree.topLevelItem(i).text(0), tree.topLevelItem(i).text(1))
        for i in range(tree.topLevelItemCount())
    ]


def ran(widget, session, wait, path):
    """Run the script from the dock, until it ends; its run."""
    widget.choose_file(path)
    widget.btnRun.click()
    wait(lambda: widget.chosen_run() is not None)
    run = session.scripts.runs[widget.chosen_run()]
    wait(lambda: not run.running, timeout=15)
    return run


def test_the_dock_is_a_base_dock_found_by_its_name(window):
    entry = window.docks.entries[SCRIPTS]
    assert (entry.title, entry.section) == ("Scripts", "Base")
    window.show_dock(SCRIPTS)
    assert window.dock_state(SCRIPTS) != "closed"
    window.set_mode("lite")
    window.show_dock(SCRIPTS)
    assert window.dock_state(SCRIPTS) != "closed"


def test_a_script_runs_and_its_output_is_shown(scripts, session, wait):
    path = written(
        session,
        "hello.py",
        "import time\nprint('Привет')\ntime.sleep(0.4)\nprint('bye')\n",
    )
    assert file_names(scripts) == ["hello.py"]
    run = ran(scripts, session, wait, path)
    wait(lambda: scripts.output.toPlainText() == "Привет\nbye\n")
    assert (run.info.status, run.info.exit_code) == ("exited", 0)
    assert run_rows(scripts)[0] == (f"{run.id} hello", "exited (0)")
    assert run.info.by == session.lab.origin
    assert not scripts.btnStop.isEnabled()
    assert not session.processes.items  # it was listed while it ran


def test_a_traceback_opens_the_script_at_its_line(scripts, session, wait, opened):
    path = written(session, "broken.py", FAILING)
    run = ran(scripts, session, wait, path)
    assert run.info.exit_code == 1
    wait(lambda: "ValueError: no bias" in scripts.output.toPlainText())
    lines = scripts.output.toPlainText().splitlines()
    place = next(i for i, line in enumerate(lines) if "line 5" in line)
    assert traceback_place(lines[place]) == (path, 5)
    block = scripts.output.document().findBlockByNumber(place)
    rect = scripts.output.blockBoundingGeometry(block).translated(
        scripts.output.contentOffset()
    )
    point = QPoint(10, int(rect.center().y()))
    QTest.mouseDClick(scripts.output.viewport(), Qt.LeftButton, pos=point)
    assert opened[-1] == ["code", str(session.workspace.folder), "--goto", f"{path}:5"]


def test_a_script_is_stopped_from_the_dock_and_from_processes(scripts, session, wait):
    session.lab.assembled.scripts.grace = 0.2  # it ignores the cancel
    path = written(session, "slow.py", SLOW)
    scripts.choose_file(path)
    scripts.btnRun.click()
    wait(lambda: scripts.chosen_run() is not None)
    run = session.scripts.runs[scripts.chosen_run()]
    wait(lambda: "waiting" in scripts.output.toPlainText())
    (process,) = session.processes.items
    assert process.title == "Script slow" and scripts.btnStop.isEnabled()
    process.stop()  # Stop in Processes
    wait(lambda: run.info.status == "stopped", timeout=10)
    wait(lambda: not session.processes.items)
    assert not scripts.btnStop.isEnabled()
    assert run_rows(scripts)[0][1].startswith("stopped")


def test_scripts_of_other_clients_and_earlier_runs_are_shown(
    new_session, wait, tmp_path
):
    other = tmp_path / "other"
    (other / "scripts").mkdir(parents=True)
    file = other / "scripts" / "elsewhere.py"
    file.write_text("print('from a terminal')\n")
    first = new_session()
    start = StartScript(path=str(file), python=(sys.executable,), workspace=str(other))
    earlier = first.call(start)
    wait(lambda: first.scripts.runs.get(earlier.id) is not None)
    wait(lambda: not first.scripts.runs[earlier.id].running, timeout=15)
    # A window opened later: the daemon lists it, its log is read when shown
    later = new_session()
    wait(lambda: earlier.id in later.scripts.runs)
    run = later.scripts.runs[earlier.id]
    assert not later.scripts.here(run) and run.output == ""
    later.scripts.output(earlier.id)
    wait(lambda: run.output == "from a terminal\n")


def test_a_new_script_comes_from_a_template(scripts, session, wait):
    titles = [action.text() for action in scripts.newMenu.actions()]
    assert titles == [t.title for t in examples.examples()]
    sweep = next(a for a in scripts.newMenu.actions() if a.text().startswith("Bias"))
    sweep.trigger()
    made = session.workspace.scripts / "sweep.py"
    assert made.read_text(encoding="utf-8") == examples.example("sweep").text
    assert scripts.chosen_file() == made and scripts.btnRun.isEnabled()
    sweep.trigger()
    assert scripts.chosen_file() == session.workspace.scripts / "sweep_2.py"
    # Files written elsewhere (VS Code, an agent) show up by themselves
    (session.workspace.scripts / "outside.py").write_text("pass\n")
    wait(lambda: "outside.py" in file_names(scripts))


def test_folders_of_scripts_are_added_to_a_workspace(
    scripts, session, tmp_path, monkeypatch
):
    scripts.offer_folders()
    assert not scripts.addFolder.isEnabled()  # no thzdaq.toml: kept nowhere
    create(session.workspace.folder, "")
    library = tmp_path.parent / f"{tmp_path.name}-library"
    (library / "tools").mkdir(parents=True)
    (library / "tools" / "calibrate.py").write_text("pass\n")
    (library / "__pycache__").mkdir()
    (library / "__pycache__" / "x.py").write_text("")
    monkeypatch.setattr(
        "thzdaq_gui.docks.scripts.QFileDialog.getExistingDirectory",
        lambda *_: str(library),
    )
    scripts.offer_folders()
    assert scripts.addFolder.isEnabled()
    scripts.add_folder()
    tops = [
        scripts.files.topLevelItem(i).text(0)
        for i in range(scripts.files.topLevelItemCount())
    ]
    assert tops == ["scripts/", f"{library.resolve().as_posix()}/"]
    assert file_names(scripts) == ["tools/calibrate.py"]
    scripts.choose_file(library.resolve() / "tools" / "calibrate.py")
    scripts.remove_folder()
    assert scripts.files.topLevelItemCount() == 1


def kept_with(text, path="scripts/scan.py", id=12):
    measurement = Measurement("script:scan", "scan", id)
    measurement.metadata[SCRIPT] = {
        "path": path,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text": text,
    }
    return measurement


def test_the_script_of_a_measurement_is_its_file_or_a_copy(session):
    text = "print('scan')\n"
    measurement = kept_with(text)
    original = written(session, "scan.py", text)
    assert session.scripts.script_of(measurement) == original
    original.write_text("print('changed since')\n")
    copy = session.scripts.script_of(measurement)
    assert copy == session.workspace.scripts / "scan_12.py"
    assert copy.read_text() == text
    assert session.scripts.script_of(measurement) == copy  # not copied again
    copy.write_text("mine now")
    assert session.scripts.script_of(measurement).name == "scan_12_2.py"
    assert session.scripts.script_of(Measurement("sis.iv_curve", "I-V", 3)) is None


def test_data_shows_the_script_of_a_measurement_in_the_dock(
    window, session, scripts, monkeypatch
):
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: told.append(a[2]))
    data = window.dataWidget
    session.measurements.add(Measurement("sis.iv_curve", "I-V", 3), None)
    data.table.selectRow(0)
    data.script()
    assert "No script measured it" in told[0]
    session.measurements.add(kept_with("print('scan')\n"), None)
    data.table.selectRow(0)
    data.script()
    copy = session.workspace.scripts / "scan_12.py"
    assert scripts.chosen_file() == copy
    assert window.dock_state(SCRIPTS) != "closed"


def test_runs_of_a_daemon_gone_are_dropped_when_it_is_asked_again(
    scripts, session, wait
):
    from thzdaq_api.scripts import ScriptInfo
    from thzdaq_gui.models.scripts import ScriptRun

    gone = ScriptInfo(
        id=99, name="old", path="old.py", command=("python",), workspace=".",
        log="elsewhere/99.log", origin="script:old@99", by="gui", pid=1,
        status="running", started="2026-11-05T10:00:00",
    )  # fmt: skip
    session.scripts.runs[99] = ScriptRun(gone)
    session.scripts.runs_changed.emit()
    assert run_rows(scripts)[0][1] == "running"
    session.scripts.load()  # as after a restart of the daemon
    wait(lambda: 99 not in session.scripts.runs)
    assert not run_rows(scripts)
