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


def test_windows_newlines_keep_byte_offsets_and_wait_for_the_lf(tmp_path):
    log = tmp_path / "1.log"
    log.write_bytes(b"one\r")
    assert read_part(str(log), 0, final=False) == ("one", 3)
    log.write_bytes(b"one\r\ntwo\r\n")
    assert read_part(str(log), 3, final=False) == ("\ntwo\n", 10)
    assert read_part(str(log), 10, final=True) == ("", 10)


def test_a_crlf_split_between_parts_is_one_newline(tmp_path, monkeypatch):
    monkeypatch.setattr(processes, "LOG_PART", 4)
    log = tmp_path / "1.log"
    log.write_bytes(b"one\r\n")
    assert read_part(str(log), 0, final=True) == ("one", 3)
    assert read_part(str(log), 3, final=True) == ("\n", 5)


def test_a_final_carriage_return_is_kept_for_progress_output(tmp_path):
    log = tmp_path / "1.log"
    log.write_bytes(b"1\r2\r")
    assert read_part(str(log), 0, final=True) == ("1\r2\r", 4)
