"""The Python of a workspace's scripts: resolved from thzdaq.toml, found
among environments (uv and conda faked by small programs), checked against
real interpreters: this one, a bare venv, one with a thzdaq of another
version."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from thzdaq_api import host, interpreters
from thzdaq_api.daemon import API_VERSION
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.interpreters import (
    CHOSEN,
    CONDA,
    OWN,
    PROJECT,
    UV,
    Environment,
    check,
    environments,
    python_in,
    scripts_python,
)
from thzdaq_api.workspace import create, write_python


def venv(folder: Path) -> Path:
    """A bare venv (no pip, no thzdaq); its interpreter."""
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(folder)], check=True
    )
    return python_in(folder)


def site_packages(python: Path) -> Path:
    done = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return Path(done.stdout.strip())


def fake_thzdaq(python: Path, version: str, api: int = API_VERSION) -> None:
    """thzdaq of version in its environment, speaking contract api."""
    site = site_packages(python)
    (site / "thzdaq").mkdir()
    (site / "thzdaq" / "__init__.py").write_text("")
    (site / "thzdaq_api").mkdir()
    (site / "thzdaq_api" / "__init__.py").write_text("")
    (site / "thzdaq_api" / "daemon.py").write_text(f"API_VERSION = {api!r}\n")
    info = site / f"thzdaq_api-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: thzdaq-api\nVersion: {version}\n"
    )


def program(path: Path, body: str) -> list:
    """A program run by this Python (it runs alike on every system)."""
    path.write_text(textwrap.dedent(body))
    return [sys.executable, str(path)]


@pytest.fixture
def bare(tmp_path) -> Path:
    return venv(tmp_path / "bare")


# thzdaq.toml
def test_an_older_file_without_a_python_runs_the_programs_own(tmp_path):
    (tmp_path / "thzdaq.toml").write_text('station = "lab"\nnotes = ""\n')
    assert interpreters.chosen(tmp_path) is None
    assert scripts_python(tmp_path) == host.script_python()
    assert scripts_python(None) == host.script_python()


def test_a_python_is_written_into_its_line_and_the_rest_stays(tmp_path, bare):
    create(tmp_path, "lab")
    path = tmp_path / "thzdaq.toml"
    path.write_text(path.read_text() + "\n# mine\nextra = 1\n")
    write_python(tmp_path, "bare")
    text = path.read_text()
    assert 'python = "bare"' in text and "# mine\nextra = 1" in text
    assert scripts_python(tmp_path) == (str(bare),)
    write_python(tmp_path, "")
    assert scripts_python(tmp_path) == host.script_python()
    assert "# mine\nextra = 1" in path.read_text()


def test_a_file_without_the_line_gets_it(tmp_path, bare):
    (tmp_path / "thzdaq.toml").write_text('station = "lab"\n')
    write_python(tmp_path, str(bare))
    assert interpreters.chosen(tmp_path) == bare
    assert 'station = "lab"' in (tmp_path / "thzdaq.toml").read_text()


def test_a_line_this_would_break_is_left_alone(tmp_path):
    path = tmp_path / "thzdaq.toml"
    path.write_text('python = """\n.venv\n"""\n')
    with pytest.raises(LabError) as e:
        write_python(tmp_path, ".venv")
    assert e.value.code == ErrorCode.INVALID_ARGUMENTS
    assert path.read_text() == 'python = """\n.venv\n"""\n'


def test_no_workspace_takes_no_python(tmp_path):
    with pytest.raises(LabError) as e:
        write_python(tmp_path, ".venv")
    assert e.value.code == ErrorCode.NOT_FOUND


def test_a_python_not_there_is_told_with_its_file(tmp_path):
    create(tmp_path, python=".venv")
    with pytest.raises(LabError) as e:
        scripts_python(tmp_path)
    assert e.value.code == ErrorCode.NOT_FOUND
    assert "thzdaq.toml" in str(e.value) and "'.venv'" in str(e.value)


def test_a_folder_or_its_interpreter_names_it(tmp_path, bare):
    assert python_in(tmp_path / "bare") == bare
    assert python_in(bare) == bare
    with pytest.raises(LabError):
        python_in(tmp_path)  # a folder with no Python in it


def test_a_kernel_runs_with_the_workspaces_python(tmp_path, bare):
    create(tmp_path, python="bare")
    command = interpreters.module_command(tmp_path, "thzdaq_api.kernel", "-f", "x")
    assert command == [str(bare), "-m", "thzdaq_api.kernel", "-f", "x"]


def test_it_is_named_relative_to_the_workspace_when_it_is_in_it(tmp_path):
    inside = tmp_path / ".venv"
    assert interpreters.stored(tmp_path, inside) == ".venv"
    elsewhere = tmp_path.parent / "other" / "python"
    assert interpreters.stored(tmp_path, elsewhere) == str(
        elsewhere.parent.resolve() / "python"
    )


def test_a_venvs_interpreter_is_not_taken_for_the_python_it_links_to(tmp_path):
    python = venv(tmp_path / ".venv")
    assert interpreters.located(python) == python
    assert (
        interpreters.stored(tmp_path, python) == python.relative_to(tmp_path).as_posix()
    )
    assert check(interpreters.located(sys.executable)).ok


# Found
def test_the_workspaces_venv_and_those_above_are_found(tmp_path):
    venv(tmp_path / ".venv")
    workspace = tmp_path / "experiment"
    venv(workspace / ".venv")
    found = environments(workspace, conda=(), uv=())
    assert found[0].kind == OWN and found[0].own
    assert [(e.kind, e.name) for e in found[1:]] == [
        (PROJECT, ".venv"),
        (PROJECT, f"{tmp_path.name}/.venv"),
    ]


def test_uv_tools_are_found(tmp_path):
    tools = tmp_path / "tools"
    venv(tools / "thzdaq")
    (tools / "broken").mkdir()  # no interpreter in it
    uv = program(
        tmp_path / "uv.py",
        f"""
        import sys
        assert sys.argv[1:] == ["tool", "dir"]
        print({str(tools)!r})
        """,
    )
    found = environments(None, conda=(), uv=uv)
    assert found[1:] == (Environment(UV, "tool thzdaq", str(tools / "thzdaq")),)


def test_conda_environments_are_found(tmp_path):
    base, science = tmp_path / "miniforge3", tmp_path / "miniforge3" / "envs" / "sci"
    conda = program(
        tmp_path / "conda.py",
        f"""
        import json, sys
        assert sys.argv[1:] == ["env", "list", "--json"]
        print(json.dumps({{"envs": [{str(base)!r}, {str(science)!r}]}}))
        """,
    )
    found = environments(None, conda=conda, uv=())
    assert found[1:] == (
        Environment(CONDA, str(base), str(base)),
        Environment(CONDA, "sci", str(science)),
    )


def test_a_conda_that_fails_finds_nothing(tmp_path):
    conda = program(tmp_path / "conda.py", "raise SystemExit(1)")
    assert environments(None, conda=conda, uv=()) == (interpreters.own(),)


def test_the_one_the_workspace_names_is_listed_and_current(tmp_path, bare):
    workspace = tmp_path / "w"
    create(workspace, python=str(bare))
    found = environments(workspace, conda=(), uv=())
    assert found[-1] == Environment(CHOSEN, str(bare), str(bare))
    assert interpreters.current(found, workspace) == found[-1]
    write_python(workspace, "")
    assert interpreters.current(found, workspace) == found[0]


def test_a_found_environment_named_by_its_interpreter_is_current(tmp_path):
    python = venv(tmp_path / ".venv")
    create(tmp_path, python=str(python))
    found = environments(tmp_path, conda=(), uv=())
    assert [e.kind for e in found] == [OWN, PROJECT]  # listed once
    assert interpreters.current(found, tmp_path) == found[1]


# Checked
def test_this_python_has_this_programs_thzdaq():
    checked = check(sys.executable)
    assert checked.ok, checked.problem
    assert checked.thzdaq == host.app_version()
    assert checked.version == interpreters.python_version()
    assert "thzdaq" in checked.text()


def test_a_python_without_thzdaq_is_told_how_to_install_it(bare):
    checked = check(bare)
    assert not checked.ok and checked.version and not checked.thzdaq
    assert "has no thzdaq" in checked.problem
    assert f"thzdaq=={host.app_version()}" in checked.hint
    assert str(bare) in checked.hint and "uv pip install" in checked.hint
    assert not checked.console


def test_another_version_of_thzdaq_is_told(bare):
    fake_thzdaq(bare, "0.0.1")
    checked = check(bare)
    assert checked.thzdaq == "0.0.1"
    assert "0.0.1" in checked.problem and host.app_version() in checked.problem
    assert f"thzdaq=={host.app_version()}" in checked.hint


def test_another_contract_is_told(bare):
    fake_thzdaq(bare, host.app_version(), api=API_VERSION + 1)
    assert "another contract" in check(bare).problem


def test_what_is_no_python_is_told(tmp_path):
    assert "not there" in check(tmp_path / "nothing").problem
    text = tmp_path / "python"
    text.write_text("not a program")
    assert not check(text).ok


def test_an_old_python_is_told():
    checked = interpreters.judged("python", {"version": "3.9.6", "console": False})
    assert "older than 3.11" in checked.problem


def test_the_programs_own_needs_no_run():
    checked = interpreters.check_own()
    assert checked.ok and checked.python == "" and checked.thzdaq == host.app_version()
