import json
from datetime import datetime
from time import time

from PySide6.QtCore import Signal

from api.SRS.LockIn_SR830 import LockIn
from threads import Thread


class state:
    meas = False


class MeasThread(Thread):
    data_signal = Signal(dict)

    def __init__(self, stop_time: float):
        self.lockin = LockIn(host="169.254.156.103")
        self.stop_time = stop_time
        super().__init__()

    def run(self):
        init_time = time()
        c_time = 0
        while c_time < self.stop_time and state.meas:
            volt = lockin.get_out3()
            c_time = time() - init_time
            self.data_signal.emit({"voltage": volt, "time": c_time})
            print(f"{c_time:.3f}; {volt:.3}")


def append_data(stream, data):
    data["time"].append(stream["time"])
    data["voltage"].append(stream["voltage"])


def save_data(data):
    with open(
        f"data/meas_stream_lockin_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump({"data": data}, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    lockin = LockIn(host="169.254.156.103")

    stop_time = 3000
    init_time = time()
    c_time = 0
    data = {
        "time": [],
        "voltage": [],
    }

    thread = MeasThread(stop_time=3000)

    thread.data_signal.connect(lambda x: append_data(x, data))
    thread.finished.connect(lambda: save_data(data))
