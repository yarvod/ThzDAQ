"""The packages on PyPI (docs/daemon.md, «Пакеты на PyPI»): one version for all,
the program's; each requires the others at exactly it; all described alike; the
client alone (thzdaq without extras) brings no numpy and no drivers.

check_packages.py checks the built wheels the same way, installed."""

import importlib.util
import shutil
import tomllib
from pathlib import Path
from typing import Dict, List, Set

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("release", ROOT / "release.py")
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)


def read(pyproject: Path) -> dict:
    return tomllib.loads(pyproject.read_text("utf-8"))["project"]


# Package folder -> its [project]
PROJECTS: Dict[Path, dict] = {
    pyproject.parent: read(pyproject) for pyproject in release.projects(ROOT)
}
BY_NAME = {canonicalize_name(p["name"]): p for p in PROJECTS.values()}


def requirements(project: dict, extras: bool = True) -> List[Requirement]:
    found = [Requirement(text) for text in project.get("dependencies", [])]
    if extras:
        for group in project.get("optional-dependencies", {}).values():
            found += [Requirement(text) for text in group]
    return found


def pins(project: dict) -> Dict[str, str]:
    """The requirements on other packages of ThzDAQ, by name."""
    return {
        canonicalize_name(r.name): str(r.specifier)
        for r in requirements(project)
        if canonicalize_name(r.name) in BY_NAME
    }


def test_every_package_has_the_version_of_the_program():
    program = release.program_version(release.VERSION_FILE)
    version = release.python_version(program)
    assert {name: p["version"] for name, p in BY_NAME.items()} == {
        name: version for name in BY_NAME
    }


def test_packages_require_each_other_at_exactly_that_version():
    for name, project in BY_NAME.items():
        exact = f"=={project['version']}"
        assert pins(project) == {other: exact for other in pins(project)}, name


def test_the_version_as_python_spells_it():
    for program, python in {
        "0.3.0": "0.3.0",
        "0.3.0-beta.2": "0.3.0b2",
        "1.0.0-rc.1": "1.0.0rc1",
        "2.1.3-alpha.4": "2.1.3a4",
    }.items():
        assert release.python_version(program) == python
        assert Version(program) == Version(python)


def test_release_stamps_the_program_and_every_package(tmp_path):
    program = tmp_path / "version.py"
    shutil.copy(release.VERSION_FILE, program)
    copies = {}
    for folder in PROJECTS:
        copy = tmp_path / folder.name / "pyproject.toml"
        copy.parent.mkdir()
        shutil.copy(folder / "pyproject.toml", copy)
        copies[copy] = PROJECTS[folder]

    release.stamp(program, list(copies), "1.2.3-rc.4")

    assert release.program_version(program) == "1.2.3-rc.4"
    for copy, before in copies.items():
        after = read(copy)
        assert after["version"] == "1.2.3rc4"
        assert pins(after) == {name: "==1.2.3rc4" for name in pins(before)}
        others = [str(r) for r in requirements(after) if r.name not in BY_NAME]
        assert others == [str(r) for r in requirements(before) if r.name not in BY_NAME]
        unchanged = set(before) - {"version", "dependencies", "optional-dependencies"}
        assert {key: after[key] for key in unchanged} == {
            key: before[key] for key in unchanged
        }


def closure(name: str) -> Set[str]:
    """The distributions a package brings without extras: ThzDAQ's and the
    first ones outside it."""
    found: Set[str] = set()
    todo = [name]
    while todo:
        current = todo.pop()
        if current not in found:
            found.add(current)
            if current in BY_NAME:
                todo += [
                    canonicalize_name(r.name)
                    for r in requirements(BY_NAME[current], extras=False)
                ]
    return found


def test_the_client_alone_brings_no_numpy_and_no_drivers():
    assert closure("thzdaq") == {"thzdaq", "thzdaq-api", "thzdaq-cli", "msgspec"}


def test_analysis_takes_the_numpy_of_a_notebook():
    # numpy<2 stays with thzdaq-core: the daemon is tested with numpy 1.x
    numpy = {r.name: r for r in requirements(BY_NAME["thzdaq-analysis"])}["numpy"]
    assert numpy.specifier.contains("2.1")


def test_every_package_is_described_alike():
    meta = BY_NAME["thzdaq"]
    for folder, project in PROJECTS.items():
        assert project["description"], folder.name
        assert (folder / project["readme"]).is_file(), folder.name
        assert project["requires-python"].startswith(">=3.11"), folder.name
        for key in ("license", "authors", "urls"):
            assert project[key] == meta[key], (folder.name, key)
        assert set(meta["classifiers"]) <= set(project["classifiers"]), folder.name
        for name in project["license-files"]:
            assert (folder / name).read_text("utf-8") == (ROOT / "LICENSE").read_text(
                "utf-8"
            ), (folder.name, name)
