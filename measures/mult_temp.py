import json
import logging
import time
from datetime import datetime

import settings
from api import TemperatureController
from api.Keithley.multimeter import Multimeter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

mult = Multimeter(host="169.254.156.103", gpib=26)
mult.set_function("F2")
mult.set_range("R4")
temp_contr = TemperatureController(
    port=1234, host="169.254.156.101", gpib=12, adapter=settings.PROLOGIX_ETHERNET
)

time_end = 7200

data = {
    "r": [],
    "ta": [],
    "tb": [],
    "tc": [],
    "time": [],
}

try:
    start_time = time.time()
    time_diff = 0
    while time_diff < time_end:
        r = mult.idn()
        try:
            r = float(r.replace("NOHM", ""))
        except ValueError:
            time_diff = time.time() - start_time
            continue
        ta = temp_contr.get_temperature_a()
        tb = temp_contr.get_temperature_b()
        tc = temp_contr.get_temperature_c()
        time_now = datetime.now().strftime("%T.%f")
        print(
            f"time: {time_now}; r: {r:.3f}Ohm; ta: {ta:.2f}K; tb: {tb:.2f}K; tc: {tc:.2f}K"
        )
        time_diff = time.time() - start_time
        data["r"].append(r)
        data["ta"].append(ta)
        data["tb"].append(tb)
        data["tc"].append(tc)
        data["time"].append(time_diff)
except (Exception, KeyboardInterrupt) as e:
    print(e)

with open(
    f"data/meas_multi_temp_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
