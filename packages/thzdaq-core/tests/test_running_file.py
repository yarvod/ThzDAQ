"""The file of a running measurement (json_store.RunningFile): its description
without records, records appended to the records file next to it, the whole
file at its end; a process killed while it runs loses no record."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from thzdaq_api.measurement_file import (
    COMPLETED,
    INTERRUPTED,
    Column,
    DeviceUse,
    read_measurement,
    records_path,
)
from thzdaq_api.measurements import PlotInfo
from thzdaq_core.adapters import json_store
from thzdaq_core.adapters.json_store import MeasurementStore
from thzdaq_core.application.runner import MeasurementRunner
from thzdaq_core.domain.measurements.procedure import Procedure


class Bench:
    def device_use(self, ref):
        return DeviceUse(ref)

    def require(self, devices, requirements, pause, planned=(), told=None):
        return {}

    def quantities(self, ref):

        return []

    def snapshot(self, refs=None):
        return {}


class Watching(Procedure):
    """Records rows, then what look() looks at on its files while it runs."""

    name = "test.watching"
    table_titles = {"watch": "Watched"}
    columns = {
        "power": Column("power", "IF power", "dBm", "power_meter_1/power"),
        "bias": Column("bias", "Bias", "V"),
    }
    rows = 5

    def __init__(self, look=lambda ctx: None):
        super().__init__()
        self.look = look

    def run(self, ctx):
        for i in range(self.rows):
            ctx.record("watch", time=i * 0.5, power=-30.0 - i)
        self.look(ctx)


def run(tmp_path, procedure, update_interval=3600.0):
    runner = MeasurementRunner(Bench(), MeasurementStore(tmp_path), (), update_interval)
    return runner.run(procedure)


def file_of(ctx):
    return ctx.measurement.metadata["path"]


def lines(path):
    return records_path(path).read_text(encoding="utf-8").splitlines()


@pytest.fixture
def described(monkeypatch):
    """The paths of the descriptions written, in order."""
    written = []
    write = json_store.write_file

    def counting(path, text):
        written.append(path)
        return write(path, text)

    monkeypatch.setattr(json_store, "write_file", counting)
    return written


def test_records_go_to_the_records_file_and_the_end_into_one_file(tmp_path, described):
    seen = {}

    def look(ctx):
        path = file_of(ctx)
        seen["file"] = json.loads(open(path, encoding="utf-8").read())
        seen["lines"] = lines(path)

    measurement = run(tmp_path, Watching(look), update_interval=0.0)
    file = seen["file"]
    assert file["status"] == "running"
    assert file["tables"]["watch"]["data"] == {"time": [], "power": []}
    assert file["tables"]["watch"]["columns"][1]["title"] == "IF power"
    assert len(seen["lines"]) == Watching.rows
    # Updated after every record: written as it started and with its table only
    assert len(described) == 2

    (path,) = tmp_path.glob("*/*")
    assert path.name == "000001_test_watching.json"
    whole = read_measurement(path)
    assert whole.status == COMPLETED == measurement.status
    assert whole.column("watch", "power") == [-30.0, -31.0, -32.0, -33.0, -34.0]


def test_a_new_column_is_described_before_its_record(tmp_path):
    seen = {}

    def look(ctx):
        ctx.record("watch", time=9.0, power=-1.0, bias=2e-3)
        seen["read"] = read_measurement(file_of(ctx))

    run(tmp_path, Watching(look))
    found = seen["read"]
    assert found.status == INTERRUPTED  # running: as a crash leaves it
    assert found.tables["watch"].get_column("bias").title == "Bias"
    assert found.column("watch", "bias") == [None] * Watching.rows + [2e-3]


def test_what_else_changes_goes_into_the_file_on_an_update(tmp_path, described):
    seen = {}
    plot = PlotInfo("p", "Power", "watch", "time", "power")

    def look(ctx):
        ctx.measurement.comment = "LO at 230 GHz"
        ctx.plot(plot)
        ctx.record("watch", time=9.0, power=-1.0)
        seen["read"] = read_measurement(file_of(ctx))

    run(tmp_path, Watching(look), update_interval=0.0)
    found = seen["read"]
    assert found.comment == "LO at 230 GHz"
    assert found.plots[-1]["key"] == "p"
    assert len(found.records("watch")) == Watching.rows + 1
    assert len(described) == 3


def test_when_records_cannot_be_written_the_whole_file_is(tmp_path, monkeypatch):
    line = json_store.record_line
    calls = []

    def failing(table, record):
        calls.append(table)
        if len(calls) > 2:
            raise OSError(28, "No space left on device")
        return line(table, record)

    monkeypatch.setattr(json_store, "record_line", failing)
    seen = {}

    def look(ctx):
        seen["read"] = read_measurement(file_of(ctx))

    run(tmp_path, Watching(look), update_interval=0.0)
    assert len(calls) == 3  # it stops trying
    assert seen["read"].column("watch", "time") == [0.0, 0.5, 1.0, 1.5, 2.0]
    (path,) = tmp_path.glob("*/*")  # the records file is gone at the end
    assert len(read_measurement(path).records("watch")) == Watching.rows


KILLED = """
import os, sys
from test_running_file import Bench, Watching
from thzdaq_core.adapters.json_store import MeasurementStore
from thzdaq_core.application.runner import MeasurementRunner

class Killed(Watching):
    rows = int(sys.argv[2])

    def __init__(self):
        super().__init__(lambda ctx: os._exit(9))  # no cleanup, no end

MeasurementRunner(Bench(), MeasurementStore(sys.argv[1])).run(Killed())
"""


def test_a_process_killed_while_it_measures_loses_no_record(tmp_path):
    rows = 2000
    killed = subprocess.run(
        [sys.executable, "-c", KILLED, str(tmp_path), str(rows)],
        cwd=Path(__file__).parent,
        timeout=60,
    )
    assert killed.returncode == 9
    (path,) = tmp_path.glob("*/*.json")
    assert records_path(path).exists()
    alone = json.loads(path.read_text(encoding="utf-8"))
    assert (
        alone["status"] == "running" and alone["tables"]["watch"]["data"]["power"] == []
    )

    found = read_measurement(path)
    assert found.status == INTERRUPTED
    assert found.column("watch", "power") == [-30.0 - i for i in range(rows)]
    assert found.tables["watch"].title == "Watched"
    assert found.tables["watch"].get_column("power").source == "power_meter_1/power"
