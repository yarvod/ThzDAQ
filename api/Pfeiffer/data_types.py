from typing import Any


class BaseType:
    id: int = None
    _initial_data: Any = None
    _value: Any = None
    name: str = "base_type"
    description: str = "Base type class"
    length: int = 0

    def __init__(self, data: Any = None, instance: Any = None):
        """
        :param data: Data in Pfeiffer typing
        :param instance: Data in Python typing
        """
        assert (data is None and instance is None) is False
        if not data:
            self._initial_data = self.to_device(instance)
        else:
            self._initial_data: Any = data
        if not instance:
            self._value = self.to_python(data)
        else:
            self._value = instance

    def __str__(self):
        return f"{self.__class__.__name__}"

    __repr__ = __str__

    @property
    def value(self):
        return self.to_python(self._initial_data)

    @property
    def value_device(self):
        return self.to_device(self._value)

    def to_python(self, value: Any):
        raise NotImplementedError

    def to_device(self, value: Any):
        raise NotImplementedError


class BooleanOld(BaseType):
    id = 0
    name = "boolean_old"
    description = "Logical value (false/true)"
    length = 6

    def to_python(self, value: str) -> bool:
        if value == "000000":
            return False
        elif value == "111111":
            return True
        raise Exception(f"Unable to transform {value} to bool")

    def to_device(self, value: bool) -> str:
        if value is True:
            return "111111"
        elif value is False:
            return "000000"
        raise Exception(f"Unable to transform {value} to str")


class UInteger(BaseType):
    id = 1
    name = "u_integer"
    description = "Positive whole number"
    length = 6

    def to_python(self, value: str) -> int:
        return int(value)

    def to_device(self, value: int) -> str:
        int_len = len(f"{value}")
        prefix = "".join(("0" for _ in range(self.length - int_len)))
        return f"{prefix}{value}"


class UReal(BaseType):
    id = 2
    name = "u_real"
    description = "Positive fixed point number"
    length = 6

    def to_python(self, value: Any) -> float:
        return float(value)

    def to_device(self, value: Any) -> str:
        cleared = f"{value}".replace(".", "")
        int_len = len(cleared)
        prefix = "".join(("0" for _ in range(self.length - int_len)))
        return f"{prefix}{value}"


class UExpo(BaseType):
    id = 3
    name = "u_expo"
    description = "Positive exponential number"
    length = 6

    def to_python(self, value: Any) -> float:
        return float(value)

    def to_device(self, value: Any):
        # TODO: create implementation
        ...


class String(BaseType):
    id = 4
    name = "string"
    description = (
        "Any character string with 6 characters. ASCII codes between 32 and 127"
    )
    length = 6

    def to_python(self, value: Any) -> str:
        return str(value)

    def to_device(self, value: Any) -> str:
        return str(value)


class BooleanNew(BaseType):
    id = 6
    name = "boolean_new"
    description = "Logical value (false/true)"
    length = 1

    def to_python(self, value: Any) -> bool:
        if value == "0":
            return False
        elif value == "1":
            return True

    def to_device(self, value: Any) -> str:
        if value is True:
            return "1"
        elif value is False:
            return "0"


class UShortInt(BaseType):
    id = 7
    name = "u_short_int"
    description = "Positive whole number"
    length = 3

    def to_python(self, value: Any) -> int:
        return int(value)

    def to_device(self, value: Any) -> str:
        int_len = len(f"{value}")
        prefix = "".join(("0" for _ in range(self.length - int_len)))
        return f"{prefix}{value}"


class UExpoNew(BaseType):
    id = 10
    name = "u_expo_new"
    description = "Positive exponential number. The last of both digits are the exponent with a deduction of 20"
    length = 6

    def to_python(self, value: Any) -> float:
        step = int(value[:-2]) - 20
        # FIXME: Not correct implementation
        return 10**step

    def to_device(self, value: Any):
        # TODO: write implementation
        ...


class String16(BaseType):
    id = 11
    name = "string16"
    description = (
        "Any character string with 16 characters. ASCII codes between 32 and 127"
    )
    length = 16

    def to_python(self, value: Any) -> str:
        return str(value)

    def to_device(self, value: Any) -> str:
        return str(value)


class String8(BaseType):
    id = 12
    name = "string8"
    description = (
        "Any character string with 16 characters. ASCII codes between 32 and 127"
    )
    length = 8

    def to_python(self, value: Any) -> str:
        return str(value)

    def to_device(self, value: Any) -> str:
        return str(value)


PFEIFFER_DATA_TYPES = {
    0: BooleanOld,
    1: UInteger,
    2: UReal,
    3: UExpo,
    4: String,
    6: BooleanNew,
    7: UShortInt,
    10: UExpoNew,
    11: String16,
    12: String8,
}
