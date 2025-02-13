import logging
from typing import List, Tuple, Union

import numpy as np
import requests
from alvar import db_to_absolute
from requests import RequestException, HTTPError

import settings
from utils import constants

logger = logging.getLogger(__name__)


def linear(x: float, a: float, b: float):
    return a * x + b


def linear_fit(x, y):
    def mean(xs):
        return sum(xs) / len(xs)

    m_x = mean(x)
    m_y = mean(y)

    def std(xs, m):
        normalizer = len(xs) - 1
        return np.sqrt(sum((pow(x1 - m, 2) for x1 in xs)) / normalizer)

    def pearson_r(xs, ys):
        sum_xy = 0
        sum_sq_v_x = 0
        sum_sq_v_y = 0

        for x1, y2 in zip(xs, ys):
            var_x = x1 - m_x
            var_y = y2 - m_y
            sum_xy += var_x * var_y
            sum_sq_v_x += pow(var_x, 2)
            sum_sq_v_y += pow(var_y, 2)
        return sum_xy / np.sqrt(sum_sq_v_x * sum_sq_v_y)

    r = pearson_r(x, y)

    b = r * (std(y, m_y) / std(x, m_x))
    a = m_y - b * m_x

    return b, a


def to_db(vec: np.ndarray):
    return 20 * np.log10(np.abs(vec))


def import_class(path: str):
    module_name = ".".join(path.split(".")[:-1])
    class_name = path.split(".")[-1]
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


def get_tn(y: np.ndarray, th: float = 300, tc: float = 77) -> Union[np.ndarray, float]:
    return (th - tc * y) / (y - 1)


def get_if_tn(hot_power, cold_power, th=300, tc=77) -> Union[np.ndarray, float]:
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


def t_if(i, v, rd, t=4):
    return (
        constants.e
        * rd
        * i
        / (2 * constants.k * np.tanh((constants.e * v) / (constants.k * t)))
    )


def m(z_sis, z_l=50):
    return 1 - np.abs((z_sis - z_l) / (z_sis + z_l)) ** 2


def t_a(m1, m2, y, t1, t2):
    return (y * t1 * m1 - m2 * t2) / (1 - y)


def calc_tta(p_if_data1, p_if_data2, v1, v2, i1, i2, rd1, rd2, t_sis):
    p1 = np.array(p_if_data1["power"])
    p2 = np.array(p_if_data2["power"])

    if p_if_data1["power_units"] == "dBm":
        p1 = db_to_absolute(p1)

    if p_if_data2["power_units"] == "dBm":
        p2 = db_to_absolute(p2)

    y = p2 / p1

    t1 = t_if(i1, v1, rd1, t_sis)
    t2 = t_if(i2, v2, rd2, t_sis)
    print(f"T {t1}; {t2}")
    print(f"Rd {rd1}; {rd2}")

    m1 = m(rd1)
    m2 = m(rd2)
    print(f"M {m1}; {m2}")

    return t_a(m1, m2, y, t1, t2)


def send_to_telegram(message: str):
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage?chat_id="
            f"-{settings.TELEGRAM_CHANNEL_ID}&text="
            f"{message}"
        )
        response.raise_for_status()
        if not response.status_code == requests.status_codes.codes.ALL_GOOD:
            logger.error(
                f"[send_to_telegram] Request to Telegram failed, status_code={response.status_code}"
            )
        logger.info(f"[send_to_telegram] message {message}")
        return response.status_code
    except (HTTPError, RequestException) as exc:
        logger.exception(
            f"[send_to_telegram] Error sending code to Telegram, {str(exc)}"
        )
        return None
