import numpy as np


def to_db(vec: np.ndarray):
    return 20 * np.log10(np.abs(vec))
