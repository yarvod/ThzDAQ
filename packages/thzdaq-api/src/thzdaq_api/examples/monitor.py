"""Monitor: device readings against time, until Stop.

The detector and the SIS bias are read at an interval, a record of the
table "samples" per reading; the IF power and the SIS current are drawn as
it goes. It runs for the duration, or until Stop: the measurement then ends
cancelled and keeps what was read.
"""

import time

from thzdaq import connect, device, plot, value

detector = device("Detector", "PowerDetector")
bias = device("SIS bias", kind="sis_bias")
interval = value("Interval", 1.0, unit="s")
duration = value("Duration", 0.0, unit="s", help="0: until Stop")
p_t = plot("P-t", table="samples", x="time", y="power")
i_t = plot("I-t", table="samples", x="time", y="current")

lab = connect()
with lab.measurement("monitor", devices=[detector, bias]) as m:
    started = time.monotonic()
    while not duration or time.monotonic() - started < duration:
        reading = bias.read()
        m.record(
            "samples",
            time=time.monotonic() - started,
            power=detector.power,
            voltage=reading.voltage,
            current=reading.current,
        )
        m.progress()
        m.sleep(interval)  # Stop ends it here

print(f"#{m.run.id} {m.run.status}: {m.run.done} readings in {m.run.path}")
