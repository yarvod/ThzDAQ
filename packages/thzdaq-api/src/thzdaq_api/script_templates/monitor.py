"""Monitor: device readings against time, until Stop.

Devices are read at an interval, a record of the table "samples" per
reading; the IF power and the SIS current are drawn as it goes. It runs for
DURATION_S, or until Stop (the Scripts dock, thzdaq script stop): the
measurement then ends cancelled and keeps what was read.
"""

import time

from thzdaq import connect

DETECTOR = "power_meter_1"
BIAS = "sis_bias_1"
INTERVAL_S = 1.0
DURATION_S = 0  # 0: until Stop

lab = connect()
detector, bias = lab[DETECTOR], lab[BIAS]

with lab.measurement(
    "monitor",
    devices=[detector, bias],
    parameters={"interval": INTERVAL_S, "duration": DURATION_S},
) as m:
    m.plot("samples", x="time", y="power", title="P-t")
    m.plot("samples", x="time", y="current", title="I-t")
    started = time.monotonic()
    while not DURATION_S or time.monotonic() - started < DURATION_S:
        reading = bias.read()
        m.record(
            "samples",
            time=time.monotonic() - started,
            power=detector.power,
            voltage=reading.voltage,
            current=reading.current,
        )
        m.progress()
        m.sleep(INTERVAL_S)  # Stop ends it here

print(f"#{m.run.id} {m.run.status}: {m.run.done} readings in {m.run.path}")
