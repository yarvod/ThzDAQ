import numpy as np


def linear(x: float, a: float, b: float):
    return a * x + b


def to_db(vec: np.ndarray):
    return 20 * np.log10(np.abs(vec))


def import_class(path: str):
    module_name = ".".join(path.split(".")[:-1])
    class_name = path.split(".")[-1]
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)
