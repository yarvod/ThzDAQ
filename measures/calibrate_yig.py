import json
import time
import logging

from datetime import datetime

from api import SpectrumBlock
from api.NationalInstruments.yig_filter import NiYIGManager
from store.state import state
from utils.functions import linear


logger = logging.getLogger(__name__)


s_block = SpectrumBlock(host="169.254.75.176", port=5025, adapter="SOCKET", delay=0.05)
ni = NiYIGManager()

results = {
    "point": [],
    "power": [],
    "freq": [],
}
point_from = 0
point_to = 4095
freq_from = 2.5e9
freq_to = 13.5e9


try:
    time_start = time.time()
    s_block.set_span_frequency(300e6)
    for point in range(point_from, point_to + 1):
        freq = round(
            linear(point, *state.CALIBRATION_DIGITAL_POINT_2_FREQ),
        )
        s_block.set_center_frequency(freq)
        resp = ni.write_task(value=point, yig="yig_1")
        resp_int = resp.get("result", None)
        if resp_int is None:
            logger.error(f"Unable set point {point}")

        if point == 0:
            time.sleep(0.5)
        time.sleep(0.15)
        s_block.peak_search()
        power = s_block.get_peak_power()
        freq = s_block.get_peak_freq()

        results["point"].append(point)
        results["power"].append(power)
        results["freq"].append(freq)

        proc = round((point + 1) / (point_to + 1) * 100, 2)
        diff_time = (time.time() - time_start) * (1 - proc / 100) / (proc / 100)
        minutes = round(diff_time // 60)
        seconds = round(diff_time % 60)
        logger.info(f"[Proc {proc} %] Time {minutes:02}:{seconds:02}")
except (Exception, KeyboardInterrupt) as e:
    logger.exception(f"{e}", exc_info=True)

with open(
    f"data/calibration_yig_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(results, f, ensure_ascii=False, indent=4)
