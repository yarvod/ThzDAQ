"""The workspace's settings offscreen: the Python of its scripts found,
checked and saved (InterpreterModel, WorkspaceSettings), and where the File
menu offers them."""

import subprocess
import sys
from pathlib import Path

import pytest
from thzdaq_api import host, interpreters
from thzdaq_api.interpreters import located, python_in
from thzdaq_api.workspace import FILE, create, read

from thzdaq_gui.models.interpreter import InterpreterModel
from thzdaq_gui.workspace import Workspace
from thzdaq_gui.workspace_settings import CHECKING, WorkspaceSettings

CHECK_S = 30.0  # a check starts an interpreter


@pytest.fixture(autouse=True)
def nothing_else(monkeypatch):
    """No uv or conda of this machine: only what a test makes is found."""
    monkeypatch.setattr(interpreters, "conda_command", lambda: ())
    monkeypatch.setattr(interpreters, "uv_command", lambda: ())


@pytest.fixture
def opened(app, wait, tmp_path):
    """The dialog of a workspace in tmp_path with a bare .venv, its
    environments found."""
    create(tmp_path)
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(tmp_path / ".venv")],
        check=True,
    )
    model = InterpreterModel(Workspace(tmp_path))
    dialog = WorkspaceSettings(model)
    wait(lambda: dialog.choices.isEnabled(), CHECK_S)
    yield dialog
    model.close()
    dialog.deleteLater()


def texts(dialog):
    return [dialog.choices.itemText(i) for i in range(dialog.choices.count())]


def checked(dialog, wait) -> str:
    wait(lambda: dialog.result.text() != CHECKING, CHECK_S)
    return dialog.result.text()


def test_the_python_is_found_checked_and_saved(opened, wait, tmp_path):
    dialog = opened
    assert texts(dialog) == [
        f"built-in: the program's own (Python {interpreters.python_version()})",
        "venv: .venv",
    ]
    assert dialog.chosen().own  # thzdaq.toml names none
    assert f"thzdaq {host.app_version()}" in checked(dialog, wait)
    assert dialog.remedy.isHidden()
    dialog.choices.setCurrentIndex(1)
    assert dialog.path.text() == str(tmp_path / ".venv")
    assert "has no thzdaq" in checked(dialog, wait)
    assert f"thzdaq=={host.app_version()}" in dialog.remedy.text()
    assert str(python_in(tmp_path / ".venv")) in dialog.remedy.text()
    assert not dialog.remedy.isHidden()
    dialog.accept()  # saved though it fails: thzdaq may be installed next
    assert read(tmp_path).python == ".venv"


def test_a_check_asked_of_a_choice_left_since_is_not_shown(opened, wait):
    dialog = opened
    dialog.choices.setCurrentIndex(1)
    dialog.choices.setCurrentIndex(0)
    wait(lambda: dialog.model.calls.pending == 0, CHECK_S)
    wait(lambda: dialog.result.text() != CHECKING, CHECK_S)
    assert f"thzdaq {host.app_version()}" in dialog.result.text()


def test_any_python_is_added_and_saved_as_its_path(opened, wait, tmp_path):
    dialog = opened
    dialog.add_python(sys.executable)
    assert texts(dialog)[-1] == f"path: {located(sys.executable)}"
    assert dialog.chosen().path == str(located(sys.executable))
    assert checked(dialog, wait).startswith("Python ")
    dialog.add_python(str(python_in(tmp_path / ".venv")))  # one listed already
    assert dialog.choices.currentIndex() == 1 and len(texts(dialog)) == 3
    dialog.choices.setCurrentIndex(2)
    dialog.accept()
    assert read(tmp_path).python == str(located(sys.executable))


def test_the_one_the_workspace_names_is_chosen_when_it_opens(app, wait, tmp_path):
    create(tmp_path, python="elsewhere/python")  # not there
    model = InterpreterModel(Workspace(tmp_path))
    dialog = WorkspaceSettings(model)
    wait(lambda: dialog.choices.isEnabled(), CHECK_S)
    assert dialog.choices.currentText() == "path: elsewhere/python"
    assert "not there" in checked(dialog, wait)
    model.close()
    dialog.deleteLater()


def test_a_broken_file_is_told(app, wait, tmp_path):
    (tmp_path / FILE).write_text("python = 3\n")
    model = InterpreterModel(Workspace(tmp_path))
    dialog = WorkspaceSettings(model)
    wait(lambda: dialog.result.text(), CHECK_S)
    assert FILE in dialog.result.text() and not dialog.choices.isEnabled()
    model.close()
    dialog.deleteLater()


def test_the_file_menu_offers_them_in_a_workspace_only(window, tmp_path):
    menu = window.workspaceMenu
    (tmp_path / "program").mkdir()
    window.session.workspace.open(tmp_path / "program")  # no thzdaq.toml
    menu.show_default()
    assert not menu.settingsAction.isEnabled()
    create(tmp_path / "experiment")
    window.session.workspace.open(tmp_path / "experiment")
    menu.show_default()
    assert menu.settingsAction.isEnabled()
    assert (
        Path(window.session.interpreters.workspace.folder)
        == (tmp_path / "experiment").resolve()
    )


def test_a_scripts_run_takes_the_workspaces_python(session, wait, tmp_path):
    folder = session.workspace.folder
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(folder / ".venv")],
        check=True,
    )
    create(folder, python=".venv")
    script = folder / "hello.py"
    script.write_text("print('hello')\n")
    session.scripts.run(script, "code:hello")
    wait(lambda: session.scripts.runs, CHECK_S)
    (run,) = session.scripts.runs.values()
    assert run.info.command[0] == str(python_in(folder / ".venv"))
