import json
import uuid
from datetime import datetime
from typing import Union, Dict, Any

from PyQt6 import QtGui
from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex
from PyQt6.QtWidgets import QFileDialog


class MeasureType:
    IV_CURVE = "iv_curve"
    CL_CURVE = "cl_curve"
    BIAS_VNA = "bias_vna"
    BIAS_POWER = "bias_power"
    GRID_BIAS_POWER = "grid_bias_power"
    GRID_CHOPPER_BIAS_POWER = "grid_chopper_bias_power"
    POWER_STREAM = "power_stream"
    VNA_REFLECTION = "vna_reflection"

    CHOICES = dict(
        (
            (IV_CURVE, "I-V curve"),
            (CL_CURVE, "CL curve"),
            (BIAS_VNA, "BIAS VNA"),
            (BIAS_POWER, "BIAS Power"),
            (GRID_BIAS_POWER, "GRID BIAS Power"),
            (GRID_CHOPPER_BIAS_POWER, "GRID Chopper BIAS Power"),
            (POWER_STREAM, "Power stream"),
            (VNA_REFLECTION, "VNA Reflection"),
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
        results = measure.data
        caption = f"Saving {measure.type_display}_{measure.finished.__str__()}"
        try:
            filepath = QFileDialog.getSaveFileName(filter="*.json", caption=caption)[0]
            if not filepath:
                return
            if not filepath.endswith(".json"):
                filepath += ".json"
            with open(filepath, "w", encoding="utf-8") as file:
                json.dump(results, file, ensure_ascii=False, indent=4)
            measure.saved = True
            measure.save()
        except (IndexError, FileNotFoundError):
            pass


class MeasureModel:
    objects = MeasureManager
    ind_attr_map = {
        0: "measure_type",
        1: "started",
        2: "finished",
        3: "saved",
    }

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
        self.id = str(uuid.uuid4())
        self.started = datetime.now()
        self.finished = finished
        self.saved = False

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

    def save(self):
        self.finished = datetime.now()
        self.objects.update_table()


class MeasureTableModel(QAbstractTableModel):
    manager = MeasureManager

    def __init__(self, data=None):
        super().__init__()
        self._data = []
        self._headers = ["Type", "Started", "Finished", "Saved"]

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
            [m.type_display, m.started, m.finished, m.saved] for m in measures
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
