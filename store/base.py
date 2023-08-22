import json
import uuid
from datetime import datetime
from typing import Union, Dict, Any, List

from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex
from PyQt6.QtWidgets import QFileDialog


class MeasureType:
    IV_CURVE = "iv_curve"
    CL_CURVE = "cl_curve"

    CHOICES = dict(
        (
            (IV_CURVE, "I-V curve"),
            (CL_CURVE, "CL curve"),
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

    def delete_by_indexes(self, indexes: List[int]) -> None:
        for ind in indexes:
            del self[ind]


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
    def delete_by_indexes(cls, indexes: List[int]) -> None:
        cls.all().delete_by_indexes(indexes)
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
        except (IndexError, FileNotFoundError):
            pass


class MeasureModel:
    objects = MeasureManager
    ind_attr_map = {
        0: "measure_type",
        1: "started",
        2: "finished",
    }

    def __init__(
        self,
        measure_type: str,
        data: Dict,
    ):
        # Validation
        self.validate_type(value=measure_type)
        # Setting attrs
        self.measure_type = measure_type
        self.data = data
        self.id = str(uuid.uuid4())
        self.started = datetime.now()
        self.finished = "--"

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
        self.objects.update_table()


class MeasureTableModel(QAbstractTableModel):
    manager = MeasureManager

    def __init__(self, data=None):
        super().__init__()
        self._data = []
        self._headers = ["Type", "Started", "Finished"]

    def data(self, index, role):
        if not self._data:
            return None
        value = self._data[index.row()][index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            if isinstance(value, datetime):
                return value.strftime("%Y-%m-%d %H:%M:%S")
            return value

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
        self._data = [[m.type_display, m.started, m.finished] for m in measures]
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
