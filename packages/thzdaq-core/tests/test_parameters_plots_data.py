import json
import math

import pytest
from thzdaq_core.data import INTERRUPTED, Dataset, DataStore, read_dataset
from thzdaq_core.data.store import DatasetWriter, dumps, loads
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements import (
    BoolParameter,
    ChoiceParameter,
    FloatListParameter,
    FloatParameter,
    IntParameter,
    PlotSpec,
    Procedure,
    Sweep,
    SweepParameter,
)
from thzdaq_instruments.units import GHZ, MV


class Demo(Procedure):
    name = "demo"
    lo = FloatParameter(
        "LO",
        default=223 * GHZ,
        unit="Hz",
        display_unit="GHz",
        display_scale=GHZ,
        minimum=0,
    )
    points = IntParameter("Points", default=3, minimum=1)
    sweep = SweepParameter(
        "Bias", default=(0, 7 * MV, 8), unit="V", display_unit="mV", display_scale=MV
    )
    biases = FloatListParameter(
        "Biases", default=(5 * MV,), unit="V", display_unit="mV", display_scale=MV
    )
    detector = ChoiceParameter("Detector", ["yig", "spectrum"], default="yig")
    hot_cold = BoolParameter("Hot/cold", default=True)
    required = FloatParameter("Required")


class TestParameters:
    def test_defaults_and_required(self):
        demo = Demo()
        assert demo.lo == 223e9 and demo.points == 3
        with pytest.raises(ProcedureError, match="required"):
            demo.required
        with pytest.raises(ProcedureError, match="required"):
            demo.validate()
        Demo(required=1).validate()

    def test_validation(self):
        with pytest.raises(ProcedureError, match="lo"):
            Demo(lo=-1)
        with pytest.raises(ProcedureError):
            Demo(points=2.5)
        with pytest.raises(ProcedureError):
            Demo(detector="vna")
        with pytest.raises(ProcedureError):
            Demo(hot_cold="yes")
        with pytest.raises(ProcedureError, match="unknown"):
            Demo(colour=1)
        with pytest.raises(ProcedureError):
            Demo(sweep=(0, 1, 0))

    def test_parse_display_units(self):
        params = Demo.parameters()
        assert params["lo"].parse("230.5") == pytest.approx(230.5e9)
        assert params["sweep"].parse("2:3:11") == Sweep(2e-3, 3e-3, 11)
        assert params["biases"].parse("5, 6;7") == pytest.approx((5e-3, 6e-3, 7e-3))
        assert params["hot_cold"].parse("off") is False
        assert params["points"].parse("5") == 5
        assert params["lo"].format(223e9) == "223 GHz"
        assert params["sweep"].format(Sweep(0, 7e-3, 8)) == "0..7 mV, 8 points"

    def test_sweep_values(self):
        sweep = Sweep(0, 7e-3, 8)
        assert sweep.values()[1] == pytest.approx(1e-3) and sweep.step == pytest.approx(
            1e-3
        )
        assert len(sweep) == 8 and Sweep(1, 2, 1).values() == [1]

    def test_json_roundtrip(self):
        demo = Demo(required=2, sweep=(1e-3, 2e-3, 3), biases=[1e-3, 2e-3])
        data = json.loads(json.dumps(demo.to_json()))
        assert Demo.from_json(data).values() == demo.values()
        assert data["sweep"] == {"start": 1e-3, "stop": 2e-3, "points": 3}

    def test_describe_for_forms(self):
        lo = Demo.parameters()["lo"].describe()
        assert (
            lo["display_unit"] == "GHz"
            and lo["display_scale"] == GHZ
            and lo["minimum"] == 0
        )
        assert Demo.parameters()["detector"].describe()["choices"] == [
            "yig",
            "spectrum",
        ]
        assert Demo.parameters()["required"].describe()["required"] is True

    def test_inherited_parameters(self):
        class More(Demo):
            extra = IntParameter("Extra", default=1)

        assert list(More.parameters())[-1] == "extra" and "lo" in More.parameters()


class TestPlotSpec:
    def test_curves_grouped_and_scaled(self):
        spec = PlotSpec(
            "p", "P-IF", "power", "frequency", "power", x_scale=GHZ, group_by=("load",)
        )
        records = [
            {"frequency": 4e9, "power": -32, "load": "cold"},
            {"frequency": 4e9, "power": -30, "load": "hot"},
            {"frequency": 5e9, "power": -31, "load": "cold"},
            {"frequency": 6e9, "load": "cold"},
        ]
        curves = spec.curves(records)
        assert curves[("cold",)] == [(4.0, -32), (5.0, -31)]
        assert curves[("hot",)] == [(4.0, -30)]
        assert spec.label(("cold",)) == "cold"

    def test_map_points(self):
        spec = PlotSpec(
            "m", "Tn", "grid", "v1", "v2", kind="map", z="tn", x_scale=MV, y_scale=MV
        )
        assert spec.point({"v1": 2e-3, "v2": 3e-3, "tn": 50}) == pytest.approx(
            (2, 3, 50)
        )


class TestDataStore:
    def test_encoding_of_complex_and_nan(self):
        value = {
            "s11": complex(0.1, -0.2),
            "tn": math.nan,
            "inf": math.inf,
            "x": [1, 2],
        }
        decoded = loads(dumps(value))
        assert decoded["s11"] == complex(0.1, -0.2) and math.isnan(decoded["tn"])
        assert decoded["inf"] == math.inf and decoded["x"] == [1, 2]

    def test_store_roundtrip(self, tmp_path):
        store = DataStore(tmp_path)
        dataset = Dataset("sis.iv_curve", title="I-V", parameters={"a": 1})
        dataset.append("iv", {"voltage": 1e-3, "current": 2e-6})
        dataset.results["rn"] = 20.0
        dataset.finish("completed")
        path = store.save(dataset)
        assert path.parent.name == dataset.started[:10] and "sis_iv_curve" in path.name
        loaded = read_dataset(path)
        assert loaded.to_dict() == dataset.to_dict()
        assert [d.id for d in store] == [dataset.id]

    def test_crash_leaves_readable_interrupted_dataset(self, tmp_path):
        dataset = Dataset("demo")
        writer = DatasetWriter(tmp_path / "run.jsonl")
        writer.write_header(dataset)
        writer.write_record("iv", {"voltage": 1.0})
        writer.close()
        with open(tmp_path / "run.jsonl", "a", encoding="utf-8") as file:
            file.write('{"type": "record", "stream": "iv", "da')  # torn line
        loaded = read_dataset(tmp_path / "run.jsonl")
        assert loaded.status == INTERRUPTED and loaded.records("iv") == [
            {"voltage": 1.0}
        ]

    def test_writer_never_overwrites(self, tmp_path):
        DatasetWriter(tmp_path / "run.jsonl").close()
        with pytest.raises(FileExistsError):
            DatasetWriter(tmp_path / "run.jsonl")
