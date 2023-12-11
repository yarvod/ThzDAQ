import time
from datetime import datetime
import json

from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter


nrx = NRXPowerMeter(delay=0)

aver_range = [1e-2, 5e-2, 1e-1, 5e-1, 1, 5, 10, 50, 100]
stop_time = 5000
data = {i: {"aver": aver, "power": [], "time": []} for i, aver in enumerate(aver_range)}
try:
    for i, aver in enumerate(aver_range):
        print(f"Start measuring with aperture time {aver} ms ...")
        nrx.set_aperture_time(aver)
        t1 = time.time()
        t = 0
        while t <= stop_time:
            power = nrx.get_power()
            t = time.time() - t1
            data[i]["power"].append(power)
            data[i]["time"].append(t)
except (Exception, KeyboardInterrupt) as e:
    print(f"Exception: {e}")


with open(
    f"data_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json", "w", encoding="utf-8"
) as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
