"""Templates of new scripts: files of the package, copied into a scripts
folder; that they run on simulators is checked against a live daemon
(thzdaq-daemon/tests/test_script_templates.py)."""

import ast

import pytest
from thzdaq_api import templates
from thzdaq_api.errors import ErrorCode, LabError

NAMES = ["hot_cold", "iv_analysis", "monitor", "sweep"]


def test_every_template_has_a_title_and_says_what_it_does():
    found = templates.templates()
    assert [t.name for t in found] == NAMES
    for template in found:
        ast.parse(template.text)
        assert template.title and "\n" not in template.title
        assert len(template.about) > 40, template.name
        assert "from thzdaq import connect" in template.text


def test_a_script_is_made_from_a_template_never_over_a_file(tmp_path):
    folder = tmp_path / "scripts"
    first = templates.create("sweep", folder)
    second = templates.create("sweep", folder)
    assert (first.name, second.name) == ("sweep.py", "sweep_2.py")
    assert first.read_text(encoding="utf-8") == templates.template("sweep").text
    second.write_text("mine")
    assert templates.create("sweep", folder).name == "sweep_3.py"
    assert second.read_text() == "mine"


def test_an_unknown_template_names_those_there_are():
    with pytest.raises(LabError) as caught:
        templates.template("nothing")
    assert caught.value.code == ErrorCode.NOT_FOUND
    assert "sweep" in caught.value.hint
