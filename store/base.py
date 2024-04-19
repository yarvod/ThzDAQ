import json
import os
from datetime import datetime
from typing import Union, Dict, Any

from PyQt5 import QtGui
from PyQt5.QtCore import QAbstractTableModel, Qt, QModelIndex
from PyQt5.QtWidgets import QFileDialog


class MeasureType:
    IV_CURVE = "iv_curve"
    CL_CURVE = "cl_curve"
    SV_VNA = "sv_vna"
    PV_CURVE = "pv_curve"
    PV_CURVE_HOT_COLD = "pv_curve_hot_cold"
    GRID_PV_CURVE = "grid_pv_curve"
    GRID_PV_CURVE_HOT_COLD = "grid_pv_curve_hot_cold"
    GRID_IA_CURVE = "grid_ia_curve"
    POWER_STREAM = "power_stream"
    TEMPERATURE_STREAM = "temperature_stream"
    SIF_VNA = "sif_vna"
    PIF_CURVE = "pif_curve"
    PIF_CURVE_HOT_COLD = "pif_curve_hot_cold"
    TA_SIS_CALIBRATION = "ta_sis_calibration"

    CHOICES = dict(
        (
            (IV_CURVE, "I-V curve"),
            (CL_CURVE, "CL-I curve"),
            (SV_VNA, "S-V VNA curve"),
            (PV_CURVE, "P-V curve"),
            (PV_CURVE_HOT_COLD, "P-V curve hot/cold"),
            (GRID_PV_CURVE, "GRID P-V curve"),
            (GRID_PV_CURVE_HOT_COLD, "GRID P-V curve hot/cold"),
            (GRID_IA_CURVE, "I-A curve"),
            (POWER_STREAM, "P-t curve"),
            (TEMPERATURE_STREAM, "T-t curve"),
            (SIF_VNA, "S-IF VNA curve"),
            (PIF_CURVE, "P-IF curve"),
            (PIF_CURVE_HOT_COLD, "P-IF curve hot/cold"),
            (TA_SIS_CALIBRATION, "Ta SIS calibration"),
        )
    )


class MeasureList(list):
    def first(self) -> Union["MeasureModel", None]:
        try:
            return self[0]
        except IndexError:
            return None

    def last(self) -> Union["MeasureModel", None]:
        try:
            return self[-1]
        except IndexError:
            return None

    def _filter(self, **kwargs) -> filter:
        def _filter(item):
            for key, value in kwargs.items():
                if not getattr(item, key, None) == value:
                    return False
            return True

        return filter(_filter, self)

    def filter(self, **kwargs) -> "MeasureList":
        return self.__class__(self._filter(**kwargs))

    def delete_by_index(self, index: int) -> None:
        del self[index]


class MeasureManager:
    table: "MeasureTableModel" = None
    _instances: MeasureList["MeasureModel"] = MeasureList()
    latest_id = 0

    @classmethod
    def create(cls, *args, **kwargs) -> "MeasureModel":
        instance = MeasureModel(*args, **kwargs)
        cls._instances.append(instance)
        return instance

    @classmethod
    def update_table(cls):
        if isinstance(cls.table, MeasureTableModel):
            cls.table.updateData()

    @classmethod
    def all(cls):
        return cls._instances

    @classmethod
    def count(cls):
        return len(cls._instances)

    @classmethod
    def filter(cls, **kwargs) -> MeasureList["MeasureModel"]:
        return cls.all().filter(**kwargs)

    @classmethod
    def get(cls, **kwargs) -> Union["MeasureModel", None]:
        filtered = cls.filter(**kwargs)
        if len(filtered) == 0:
            return None
        return filtered[0]

    @classmethod
    def delete_by_index(cls, index: int) -> None:
        cls.all().delete_by_index(index)
        cls.update_table()

    @classmethod
    def save_by_index(cls, index: int) -> None:
        measure = cls.all()[index]
        results = measure.to_json()
        caption = f"Saving {measure.type_display} started at {measure.started.strftime('%Y-%m-%d %H:%M:%S')}"
        try:
            filepath = QFileDialog.getSaveFileName(filter="*.json", caption=caption)[0]
            if not filepath:
                return
            if not filepath.endswith(".json"):
                filepath += ".json"
            with open(filepath, "w", encoding="utf-8") as file:
                json.dump(results, file, ensure_ascii=False, indent=4)
            measure.saved = True
            measure.save(finish=False)
        except (IndexError, FileNotFoundError):
            pass

    @classmethod
    def save_all(cls):
        data = [m.to_json() for m in cls.all()]
        if not data:
            return
        if not os.path.exists("dumps"):
            os.mkdir("dumps")
        filepath = f"dumps/dump_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)


class MeasureModel:
    objects = MeasureManager
    ind_attr_map = {
        0: "id",
        1: "measure_type",
        2: "comment",
        3: "started",
        4: "finished",
        5: "saved",
    }
    type_class = MeasureType

    def __init__(
        self,
        measure_type: str,
        data: Dict,
        finished: Any = "--",
    ):
        # Validation
        self.validate_type(value=measure_type)
        # Setting attrs
        self.measure_type = measure_type
        self.data = data
        self.objects.latest_id += 1
        self.id = self.objects.latest_id
        self.started = datetime.now()
        self.finished = finished
        self.saved = False
        self.comment = ""

    @staticmethod
    def validate_type(value: str) -> None:
        if value not in MeasureType.CHOICES.keys():
            raise Exception(f"Type '{value}' is not presented in ExperimentType")

    @property
    def type_display(self) -> Union[str, None]:
        return MeasureType.CHOICES.get(self.measure_type)

    def get_attr_by_ind(self, ind: int):
        attr = self.ind_attr_map.get(ind)
        if attr:
            return getattr(self, attr)

    def save(self, finish: bool = True):
        if finish:
            self.finished = datetime.now()
        self.objects.update_table()

    def to_json(self):
        finished = self.finished
        if finished == "--":
            finished = datetime.now()
        return {
            "id": self.id,
            "comment": self.comment,
            "type": self.measure_type,
            "measure": self.type_display,
            "started": self.started.strftime("%Y-%m-%d %H:%M:%S"),
            "finished": finished.strftime("%Y-%m-%d %H:%M:%S"),
            "data": self.data,
        }


class MeasureTableModel(QAbstractTableModel):
    manager = MeasureManager

    def __init__(self, data=None):
        super().__init__()
        self._data = []
        self._headers = ["Id", "Type", "Comment", "Started", "Finished", "Saved"]

    def data(self, index, role):
        if not self._data:
            return None
        value = self._data[index.row()][index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            if isinstance(value, datetime):
                return value.strftime("%H:%M:%S")
            return value
        if role == Qt.ItemDataRole.DecorationRole:
            if isinstance(value, bool):
                if value:
                    return QtGui.QIcon("assets/yes-icon.png")
                return QtGui.QIcon("assets/no-icon.png")
            return value
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter

    def setData(self, index: QModelIndex, value: Any, role: int = ...) -> bool:
        if index.isValid() and role == Qt.ItemDataRole.EditRole:
            row = index.row()
            col = index.column()
            self._data[row][col] = value
            self.dataChanged.emit(index, index)
            return True
        return False

    def updateData(self):
        self.beginResetModel()
        measures = self.manager.all()
        self._data = [
            [m.id, m.type_display, m.comment, m.started, m.finished, m.saved]
            for m in measures
        ]
        self.endResetModel()

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return str(self._headers[section])
            elif orientation == Qt.Orientation.Vertical:
                return str(section + 1)
        return None

    def rowCount(self, index):
        # The length of the outer list.
        return len(self._data)

    def columnCount(self, index):
        return len(MeasureModel.ind_attr_map)


if __name__ == "__main__":
    d = MeasureModel.objects.create(measure_type=MeasureType.IV_CURVE, data={})
    print(MeasureModel.objects.filter(measure_type="iv_curve"))
