import subprocess
import sys

from thzdaq_api.atomic import file_access, read_bytes


def test_file_access_is_shared_by_processes(tmp_path):
    path = tmp_path / "data.json"
    code = (
        "from pathlib import Path\n"
        "from thzdaq_api.atomic import file_access\n"
        "try:\n"
        f"    with file_access(Path({str(path)!r}), timeout=0): pass\n"
        "except TimeoutError:\n"
        "    raise SystemExit(3)\n"
    )
    with file_access(path):
        held = subprocess.run([sys.executable, "-c", code], timeout=5)
    free = subprocess.run([sys.executable, "-c", code], timeout=5)
    assert held.returncode == 3 and free.returncode == 0


def test_a_process_that_exits_leaves_no_file_access_lock(tmp_path):
    path = tmp_path / "data.json"
    code = (
        "import os\n"
        "from pathlib import Path\n"
        "from thzdaq_api.atomic import file_access\n"
        f"with file_access(Path({str(path)!r})): os._exit(0)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=5)
    with file_access(path, timeout=0):
        pass


def test_reading_needs_no_lock_file_next_to_the_data(tmp_path):
    path = tmp_path / "data.json"
    path.write_bytes(b"readable")
    assert read_bytes(path) == b"readable"
    assert list(tmp_path.iterdir()) == [path]
