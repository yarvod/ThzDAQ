"""The workspace of a window: the File menu, Data by workspace, its profile."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox
from thzdaq_api import host
from thzdaq_api.measurements import StartMeasurement, WaitMeasurement
from thzdaq_api.procedures import IV_CURVE
from thzdaq_api.workspace import create, read

from thzdaq_gui import external_editor, workspace_menu
from thzdaq_gui.settings import DEFAULT_WORKSPACE, EDITOR, app_dir, settings
from thzdaq_gui.workspace import Workspace, default_workspace

QUICK_IV = dict(
    procedure=IV_CURVE,
    parameters={
        "voltage": {"start": 0, "stop": 0.001, "points": 3},
        "settle_time": 0,
        "first_point_delay": 0,
    },
    devices={"bias": "sis_bias_1"},
)


@pytest.fixture
def cli(session):
    lab = session.lab_of(True)
    lab.origin = "cli"
    return lab


def measured(lab, folder):
    run = lab.call(StartMeasurement(**QUICK_IV, workspace=str(folder)))
    return lab.call(WaitMeasurement(id=run.id, timeout=10))


def shown(window):
    """What the Data table shows: the measurement column."""
    view = window.dataWidget.shown
    return [view.index(row, 1).data() for row in range(view.rowCount())]


def test_a_workspace_is_opened_remembered_and_made_the_default(app, tmp_path):
    settings().remove(DEFAULT_WORKSPACE)
    workspace = Workspace(tmp_path / "a")
    told = []
    workspace.changed.connect(lambda: told.append(workspace.folder))
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    workspace.open(tmp_path / "b")
    workspace.open(tmp_path / "c")
    workspace.open(tmp_path / "b")
    assert told == [(tmp_path / f).resolve() for f in ("b", "c", "b")]
    assert workspace.recent()[:2] == [
        (tmp_path / "b").resolve(),
        (tmp_path / "c").resolve(),
    ]
    assert default_workspace() == app_dir() and not workspace.is_default()
    workspace.make_default(True)
    assert default_workspace() == (tmp_path / "b").resolve() and workspace.is_default()
    workspace.make_default(False)
    assert default_workspace() == app_dir()


def test_the_title_names_the_workspace(window, session, tmp_path):
    assert window.windowTitle().startswith(f"{tmp_path.name} — ThzDAQ")
    create(tmp_path / "experiment")
    session.workspace.open(tmp_path / "experiment")
    assert window.windowTitle().startswith("experiment — ThzDAQ")
    assert session.data_root == (tmp_path / "experiment" / "data").resolve()


def test_data_shows_the_workspaces_own_and_others_on_asking(
    window, session, cli, wait, tmp_path
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    measured(cli, tmp_path)
    measured(cli, elsewhere)
    wait(lambda: len(session.measurements.items) == 2)
    assert shown(window) == ["SIS I-V curve"]
    window.dataWidget.othersButton.setChecked(True)
    assert shown(window) == ["SIS I-V curve · from elsewhere", "SIS I-V curve"]
    window.dataWidget.othersButton.setChecked(False)
    session.workspace.open(elsewhere)
    assert shown(window) == ["SIS I-V curve"]
    window.dataWidget.table.selectRow(0)
    (chosen,) = window.dataWidget.selected()
    assert Path(chosen.metadata["path"]).parents[1] == elsewhere.resolve() / "data"


def test_runs_that_ended_before_the_window_are_remembered(
    connect, new_session, tmp_path
):
    lab = connect(True)
    ended = measured(lab, tmp_path)
    session = new_session()
    (row,) = session.measurements.rows
    assert row.run is not None and row.measurement.size == 0  # not read yet
    assert session.measurements.measured() == []
    loaded = session.measurements.measurement(0)
    assert loaded.id == ended.id and loaded.size == 3
    assert session.measurements.measured() == [loaded]


def test_a_workspace_that_expects_another_profile_asks_to_switch(
    window, session, monkeypatch, tmp_path, profile, wait
):
    (tmp_path / "stations").mkdir()
    shutil.copy(profile, tmp_path / "stations" / "other.yaml")
    create(tmp_path / "experiment", "other")
    asked = []

    def question(parent, title, text, *rest):
        asked.append(text)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    session.workspace.open(tmp_path / "experiment")
    assert "expects the profile 'other'" in asked[0] and "'bench'" in asked[0]
    other = str((tmp_path / "stations" / "other.yaml").resolve())
    wait(lambda: session.profile().path == other)  # station_changed is heard
    session.workspace.open(tmp_path)  # expects none: nothing asked
    assert len(asked) == 1


def test_a_new_workspace_is_made_and_opened(window, session, monkeypatch, tmp_path):
    folder = tmp_path / "new"

    def filled(dialog):
        assert dialog.station.text() == "bench"  # the daemon's profile
        dialog.folder.setText(str(folder))
        dialog.agents.setChecked(True)
        return QDialog.Accepted

    monkeypatch.setattr(workspace_menu.NewWorkspace, "exec", filled)
    monkeypatch.setattr(QMessageBox, "warning", pytest.fail)
    window.workspaceMenu.new()
    assert read(folder).station == "bench"
    assert (folder / "scripts").is_dir() and (folder / ".mcp.json").exists()
    assert session.workspace.folder == folder.resolve()


def test_a_workspace_opens_in_vs_code_or_the_editor_chosen(
    window, session, monkeypatch, tmp_path
):
    opened = []
    monkeypatch.setattr(host, "start_apart", opened.append)
    monkeypatch.setattr(external_editor, "code_command", lambda: "code")
    window.workspaceMenu.open_in_editor()
    folder = str(session.workspace.folder)
    assert opened == [["code", folder]]

    monkeypatch.setattr(external_editor, "code_command", lambda: None)
    settings().remove(EDITOR)
    editor = tmp_path / "editor"
    editor.write_text("")
    chosen = []

    def choose(*_):
        chosen.append(True)
        return str(editor), ""

    monkeypatch.setattr(external_editor.QFileDialog, "getOpenFileName", choose)
    window.workspaceMenu.open_in_editor()
    window.workspaceMenu.open_in_editor()  # asked once
    assert chosen == [True] and opened[1:] == [[str(editor), folder]] * 2
    settings().remove(EDITOR)


def test_recent_workspaces_are_in_the_file_menu(window, session, tmp_path):
    create(tmp_path / "earlier")
    session.workspace.open(tmp_path / "earlier")
    session.workspace.open(tmp_path)
    menu = window.workspaceMenu.recentMenu
    window.workspaceMenu.fill_recent()
    texts = [action.text() for action in menu.actions()]
    assert texts[0] == str((tmp_path / "earlier").resolve())
    assert str(tmp_path.resolve()) not in texts  # the open one
    menu.actions()[0].trigger()
    assert session.workspace.folder == (tmp_path / "earlier").resolve()
