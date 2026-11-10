"""Examples of the bench's own measurements: files of the package, copied into
the library; each declares its form, and that they run on simulators is
checked against a live daemon (thzdaq-daemon/tests/test_examples.py)."""

import ast

import pytest
from thzdaq_api import examples
from thzdaq_api.custom import declared_names
from thzdaq_api.errors import ErrorCode, LabError

NAMES = ["hot_cold", "iv_analysis", "map", "monitor", "raw_instrument", "sweep"]


def test_every_example_has_a_title_says_what_it_does_and_declares_its_form():
    found = examples.examples()
    assert [e.name for e in found] == NAMES
    for example in found:
        ast.parse(example.text)
        assert example.title and "\n" not in example.title
        assert len(example.about) > 40, example.name
        assert "from thzdaq import connect, " in example.text
        declared = {kind for kind, _ in declared_names(example.text)}
        assert "value" in declared, example.name
        assert declared & {"device", "instrument"}, example.name  # what it uses


def test_a_script_is_made_from_an_example_never_over_a_file(tmp_path):
    folder = tmp_path / "measurements"
    first = examples.create("sweep", folder)
    second = examples.create("sweep", folder)
    assert (first.name, second.name) == ("sweep.py", "sweep_2.py")
    assert first.read_text(encoding="utf-8") == examples.example("sweep").text
    second.write_text("mine")
    assert examples.create("sweep", folder).name == "sweep_3.py"
    assert second.read_text() == "mine"


def test_an_unknown_example_names_those_there_are():
    with pytest.raises(LabError) as caught:
        examples.example("nothing")
    assert caught.value.code == ErrorCode.NOT_FOUND
    assert "sweep" in caught.value.hint
