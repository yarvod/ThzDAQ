"""A measurement's data as a model reads it: its records thinned evenly, told as
CSV with units; its I-V analysis told in Ω, mV and µA."""

import math
import re

import msgspec
import pytest
from thzdaq_api import guides, present, tools, wire
from thzdaq_api.analysis import IVAnalysis, IVGap, IVLine, MeasurementIv
from thzdaq_api.data import encode_values
from thzdaq_api.devices import Prefix
from thzdaq_api.measurements import (
    ROWS,
    ColumnSummary,
    MeasurementRows,
    ReadMeasurement,
    RunInfo,
    thinned,
)

SI = tuple(Prefix(name, factor, "") for name, factor in (("µ", 1e-6), ("m", 1e-3), ("", 1.0)))  # fmt: skip


def run(status="completed") -> RunInfo:
    return RunInfo(12, "sis.current_vs_voltage", "SIS I-V curve", status, {}, "test")


@pytest.mark.parametrize(
    "records, limit, step, count",
    [(11, 200, 1, 11), (11, 4, 4, 4), (351, 12, 32, 12), (3510, 200, 18, 196),
     (3510, 2000, 2, 1756), (5, 2, 4, 2), (0, 200, 1, 0)],
)  # fmt: skip
def test_a_long_table_is_thinned_evenly_from_its_first_record_to_its_last(
    records, limit, step, count
):
    found, kept = thinned(records, limit)
    assert (found, len(kept)) == (step, count) and len(kept) <= limit
    if records:
        assert kept[0] == 0 and kept[-1] == records - 1
        assert all(b - a == step for a, b in zip(kept, kept[1:-1]))


def test_its_arguments_travel_with_their_defaults():
    read = wire.decode_arguments("read_measurement", b'{"id": 3}')
    assert read == ReadMeasurement(id=3) and read.limit == ROWS
    assert read.table is None and read.columns == ()


def rows(status="completed", step=18, records=3510) -> MeasurementRows:
    return MeasurementRows(
        run=run(status),
        table="iv",
        title="I-V",
        columns=(
            ColumnSummary("voltage", "Voltage", "V", 0.0, 7e-3, SI),
            ColumnSummary("current", "Current", "A", -2e-6, 3.64e-4, SI),
            ColumnSummary("load", "Load"),
            ColumnSummary("point", "Point", "", 0, 3509),
        ),
        rows=tuple(
            tuple(encode_values(v) for v in row)
            for row in (
                (0.0, 0.0, "hot, then cold", 0),
                (2.8125e-3, math.nan, None, 18),
                (7e-3, 3.64e-4, "cold", 3509),
            )
        ),
        records=records,
        step=step,
    )


def test_records_are_told_as_csv_in_the_prefix_of_each_columns_largest_value():
    found = msgspec.json.decode(msgspec.json.encode(rows()), type=MeasurementRows)
    assert present.records(found).splitlines() == [
        "#12 SIS I-V curve (completed), table iv: 3 of 3510 records, every 18th "
        "and the last",
        "voltage [mV],current [µA],load,point",
        '0,0,"hot, then cold",0',
        "2.8125,nan,--,18",
        "7,364,cold,3509",
    ]


@pytest.mark.parametrize(
    "status, step, records, head",
    [
        ("completed", 1, 3, "table iv: 3 records"),
        ("running", 1, 3, "(running), table iv: 3 records so far"),
        ("running", 2, 5, "table iv: 3 of 5 records so far, every 2nd\n"),
        ("completed", 21, 43, "3 of 43 records, every 21st\n"),
    ],
)
def test_the_head_tells_how_the_records_were_thinned(status, step, records, head):
    assert head in present.records(rows(status, step, records))


def test_an_iv_analysis_is_told_in_ohm_millivolts_and_microamperes():
    analysis = IVAnalysis(
        rn=IVLine(19.23, 0.052, -1e-5, (4e-3, 7e-3), (5e-3, 2.6e-4)),
        rj=IVLine(500.0, 0.002, 0.0, (0.0, 2.8e-3), (2e-5, 4e-8)),
        q=26.0,
        r_squared=0.99998,
        gap=IVGap(2.809e-3, 1.427e-4, (2.7e-3, 6e-6), (2.9e-3, 1.5e-4)),
    )
    found = MeasurementIv(12, "iv", "voltage", "current", 351, analysis)
    assert present.iv(found).splitlines() == [
        "#12 I-V, table iv (voltage, current; 351 points):",
        "Rn = 19.23 Ω (fit 4..7 mV, R² = 1.0000)",
        "Rj = 500 Ω (tangent at 0.02 mV)",
        "Q = Rj/Rn = 26",
        "gap 2.809 mV, current step 142.7 µA",
    ]
    stepless = msgspec.structs.replace(
        found, analysis=msgspec.structs.replace(analysis, gap=None)
    )
    assert present.iv(stepless).endswith("no current step found: gap_from and "
                                         "gap_to narrow the search")  # fmt: skip


def test_the_agents_guide_names_tools_there_are():
    section = guides.section(guides.AGENTS, "Tools of the MCP server `thzdaq`")
    named = {
        name
        for line in section.splitlines()
        if line.startswith("| `")
        for name in re.findall(r"`([a-z_]+)", line.split("|")[1])
    }
    known = tools.by_name(tools.tools(lambda: None))
    assert {"read_measurement", "analyze_measurement_iv"} <= named
    assert named - set(known) == set()
