import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Union, Dict


class MeasureType:
    IV_CURVE = "iv_curve"
    CL_CURVE = "cl_curve"

    CHOICES = dict((
        (IV_CURVE, "I-V curve"),
        (CL_CURVE, "CL curve"),
    ))


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

    def filter(self, **kwargs) -> "MeasureList":
        def _filter(item):
            for key, value in kwargs.items():
                if not getattr(item, key, None) == value:
                    return False
            return True

        return self.__class__(filter(_filter, self))


class MeasureManager:
    _instances: MeasureList["MeasureModel"] = MeasureList()

    @classmethod
    def create(cls, *args, **kwargs) -> "MeasureModel":
        instance = MeasureModel(*args, **kwargs)
        cls._instances.append(instance)
        return instance

    @classmethod
    def all(cls):
        return cls._instances

    @classmethod
    def filter(cls, **kwargs) -> MeasureList["MeasureModel"]:
        return cls.all().filter(**kwargs)

    @classmethod
    def get(cls, **kwargs) -> Union["MeasureModel", None]:
        filtered = cls.filter(**kwargs)
        if len(filtered) == 0:
            return None
        return filtered[0]


@dataclass
class MeasureModel:
    measure_type: str
    data: Dict
    id: str = str(uuid.uuid4())
    created: datetime = datetime.now()
    objects = MeasureManager

    def __post_init__(self):
        self.validate_type(value=self.measure_type)

    @staticmethod
    def validate_type(value: str) -> None:
        if value not in MeasureType.CHOICES.keys():
            raise Exception(f"Type '{value}' is not presented in ExperimentType")

    @property
    def type_display(self) -> Union[str, None]:
        return MeasureType.CHOICES.get(self.measure_type)


if __name__ == "__main__":
    d = MeasureModel.objects.create(measure_type=MeasureType.IV_CURVE, data={})
    print(MeasureModel.objects.filter(measure_type="iv_curve"))
