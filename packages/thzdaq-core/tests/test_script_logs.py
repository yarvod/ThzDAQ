"""A script's log read in parts as it grows: a character the script has not
finished writing waits for the next part, unless the script ended."""

from thzdaq_core.application import processes
from thzdaq_core.application.processes import read_part


def test_a_cut_character_waits_for_its_rest(tmp_path):
    log = tmp_path / "1.log"
    whole = "a Пётр\n".encode()
    log.write_bytes(whole[:4])  # "a П" and the first byte of "ё"
    assert read_part(str(log), 0, final=False) == ("a П", 4)
    log.write_bytes(whole)
    assert read_part(str(log), 4, final=False) == ("ётр\n", len(whole))


def test_an_ended_scripts_cut_character_is_told(tmp_path):
    log = tmp_path / "1.log"
    log.write_bytes("Пётр".encode()[:3])
    text, after = read_part(str(log), 0, final=True)
    assert (text, after) == ("П�", 3)


def test_a_long_log_comes_in_parts_of_whole_characters(tmp_path, monkeypatch):
    monkeypatch.setattr(processes, "LOG_PART", 5)
    log = tmp_path / "1.log"
    log.write_bytes("ПППП".encode())  # 8 bytes: a part of 5 cuts the third
    parts, since = [], 0
    while True:
        text, since = read_part(str(log), since, final=True)
        if not text:
            break
        parts.append(text)
    assert parts == ["ПП", "ПП"] and since == 8


def test_no_log_yet_is_no_text(tmp_path):
    assert read_part(str(tmp_path / "none.log"), 0, final=False) == ("", 0)
