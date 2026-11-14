"""Reading a measurement file with the records its writer appended next to it:
a file still marked running gets them, one that ended is whole."""

import json
import math
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from thzdaq_api.measurement_file import (
    COMPLETED,
    INTERRUPTED,
    Column,
    Measurement,
    read_measurement,
    record_line,
    records_path,
    write_file,
    write_measurement,
)

STARTED = "2026-11-05T10:00:00.000"


def running(tmp_path, rows=0):
    """A running monitor whose file holds rows records and its description."""
    measurement = Measurement("monitor.values_vs_time", "Monitor", 7, started=STARTED)
    table = measurement.table("watch", "Watched")
    table.columns.append(Column("power", "Power", "dBm", "power_meter_1/power"))
    table.data["power"] = []
    for i in range(rows):
        measurement.append("watch", {"power": -float(i)})
    path = tmp_path / "2026-11-05" / "000007_monitor_values_vs_time.json"
    return measurement, path


def append(path, *lines):
    with open(records_path(path), "a", encoding="utf-8", newline="\n") as file:
        file.writelines(lines)


def test_reading_does_not_prevent_replacing_a_measurement(tmp_path):
    first, path = running(tmp_path)
    first.finish(COMPLETED, STARTED)
    first.comment = "first"
    second = Measurement.from_dict(first.to_dict())
    second.comment = "second"
    write_measurement(first, path)
    start = Barrier(3)

    def publish(measurement):
        start.wait()
        for _ in range(100):
            write_measurement(measurement, path)

    def discover():
        start.wait()
        for _ in range(100):
            assert read_measurement(path).comment in ("first", "second")

    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(publish, first), pool.submit(publish, second)]
        jobs.append(pool.submit(discover))
        for job in jobs:
            job.result(timeout=10)


def test_the_records_file_lies_next_to_the_measurement(tmp_path):
    path = tmp_path / "2026-11-05" / "000007_monitor_values_vs_time.json"
    assert records_path(path) == path.with_name("000007_monitor_values_vs_time.jsonl")


def test_a_running_file_gets_its_records_from_the_records_file(tmp_path):
    measurement, path = running(tmp_path)
    write_file(path, json.dumps(measurement.to_dict(records=False)))
    append(path, *(record_line("watch", {"power": -float(i)}) for i in range(3)))
    append(path, record_line("watch", {"power": math.nan, "time": 1.5}))

    found = read_measurement(path)
    assert found.status == INTERRUPTED
    assert found.column("watch", "power")[:3] == [0.0, -1.0, -2.0]
    assert math.isnan(found.column("watch", "power")[3])
    assert found.column("watch", "time") == [None, None, None, 1.5]
    watch = found.tables["watch"]
    assert watch.title == "Watched"
    assert watch.get_column("power").source == "power_meter_1/power"
    assert watch.get_column("time").unit == "s"  # a known key


def test_a_line_cut_short_by_a_crash_is_left_out(tmp_path):
    measurement, path = running(tmp_path)
    write_file(path, json.dumps(measurement.to_dict(records=False)))
    line = record_line("watch", {"power": 1.0, "device": "мощность"})
    append(path, line, line)
    with open(records_path(path), "ab") as file:
        file.write(line.encode("utf-8")[:-15])  # inside a Cyrillic letter

    assert read_measurement(path).column("watch", "power") == [1.0, 1.0]


def test_records_the_file_holds_already_are_not_taken_twice(tmp_path):
    """The whole file of a running measurement (its records file failed)."""
    measurement, path = running(tmp_path, rows=3)
    write_measurement(measurement, path)
    append(path, *(record_line("watch", {"power": -float(i)}) for i in range(2)))
    append(path, record_line("other", {"x": 1.0}))
    assert read_measurement(path).column("watch", "power") == [0.0, -1.0, -2.0]
    assert read_measurement(path).column("other", "x") == [1.0]

    append(path, *(record_line("watch", {"power": -float(i)}) for i in range(2, 5)))
    assert read_measurement(path).column("watch", "power") == [-0.0, -1, -2, -3, -4]


def test_a_measurement_that_ended_is_whole_without_its_records_file(tmp_path):
    measurement, path = running(tmp_path, rows=2)
    measurement.finish(COMPLETED, STARTED)
    write_measurement(measurement, path)
    append(path, record_line("watch", {"power": 5.0}))  # left by a crash

    found = read_measurement(path)
    assert found.status == COMPLETED
    assert found.column("watch", "power") == [0.0, -1.0]


def test_a_file_older_than_records_files_reads_as_before(tmp_path):
    measurement, path = running(tmp_path, rows=2)
    write_measurement(measurement, path)
    found = read_measurement(path)
    assert found.status == INTERRUPTED
    assert found.to_dict()["tables"] == measurement.to_dict()["tables"]
