import logging
from typing import List, Tuple

import numpy as np
from alvar import db_to_absolute

logger = logging.getLogger(__name__)


def linear(x: float, a: float, b: float):
    return a * x + b


def to_db(vec: np.ndarray):
    return 20 * np.log10(np.abs(vec))


def import_class(path: str):
    module_name = ".".join(path.split(".")[:-1])
    class_name = path.split(".")[-1]
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


def get_tn(y: np.ndarray, th: float = 300, tc: float = 77):
    return (th - tc * y) / (y - 1)


def get_if_tn(hot_power, cold_power, th=300, tc=77):
    y_w = db_to_absolute(hot_power) / db_to_absolute(cold_power)
    t = get_tn(y=y_w, th=th, tc=tc)
    return t


def get_voltage_tn(
    hot_power: List,
    cold_power: List,
    hot_voltage: List,
    cold_voltage: List,
    th: float = 300,
    tc: float = 77,
    window: int = 10,
) -> Tuple[List, List, List]:
    hot = np.array(hot_power)
    cold = np.array(cold_power)
    volt_cold = np.array(cold_voltage)
    volt_hot = np.array(hot_voltage)

    indexes = min(len(volt_cold), len(volt_hot))
    left_offset = int(window // 2)
    right_offset = int(left_offset + window % 2)

    y_factor = []
    t = []
    volt = []
    for i in range(indexes):
        min_ind = i - left_offset if i - left_offset >= 0 else i
        max_ind = i + right_offset if i + right_offset <= indexes else indexes + 1
        volt_diff = np.abs(volt_cold[min_ind:max_ind] - volt_hot[i])
        try:
            min_volt_cold_ind = np.where(volt_diff == np.min(volt_diff))[0] + min_ind
        except IndexError:
            logger.warning(f"Unable to find nearest voltage to {volt_hot[i]}")
            continue
        y_db = hot[i] - cold[min_volt_cold_ind]
        y_w = db_to_absolute(hot[i]) / db_to_absolute(cold[min_volt_cold_ind])
        y_factor.append(y_db[0])
        t.append(get_tn(y=y_w, th=th, tc=tc)[0])
        volt.append(volt_hot[i])

    return volt, y_factor, t
