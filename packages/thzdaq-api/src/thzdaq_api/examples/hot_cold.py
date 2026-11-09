"""Hot/cold P-V: Y-factor and noise temperature against bias.

IF power against bias on the hot and the cold load: the chopper turns to
each load in turn and the bias is swept on each. The table "pv" holds both
sweeps, "y_factor" what follows from them. The bias goes back and the cold
load is set however the measurement ends. Needs the analysis package
(thzdaq[analysis]; the program has it).
"""

import math

from thzdaq import connect, device, plot, value
from thzdaq_analysis.noise import match_hot_cold, noise_temperature

bias = device("SIS bias", kind="sis_bias")
detector = device("Detector", "PowerDetector")
load = device("Load", "LoadSwitch")  # turns to the hot or the cold load
voltage = value("Bias voltage", "0:7:351", unit="mV")
t_hot = value("Hot load", 300, unit="K")
t_cold = value("Cold load", 77, unit="K")
load_settle = value("Load settle", 2, unit="s", help="after the load turns")
settle = value("Settle", 10, unit="ms", help="after each bias step")
pv = plot("P-V", table="pv", x="voltage", y="power", group_by="load")
tn = plot("Tn-V", table="y_factor", x="voltage", y="noise_temperature")

lab = connect()
with lab.measurement(
    "pv_hot_cold",
    devices=[bias, detector, load],
    exclusive=[bias],
    total=2 * voltage.points,
) as m:
    m.restore(bias, "voltage_set")
    m.on_exit(load, "to_cold")  # the daemon turns to the cold load at the end
    sweeps = {}
    for state in ("hot", "cold"):
        getattr(load, f"to_{state}")()
        m.sleep(load_settle)
        points = []
        for v in m.sweep(voltage):
            bias.voltage_set = v
            m.sleep(settle)
            reading = bias.read()
            power = detector.power
            m.record(
                "pv",
                load=state,
                voltage_set=v,
                voltage=reading.voltage,
                current=reading.current,
                power=power,
            )
            points.append((reading.voltage, power))
            m.progress()
        sweeps[state] = points
    best = math.inf
    for v, hot, cold in match_hot_cold(sweeps["hot"], sweeps["cold"]):
        temperature = noise_temperature(hot, cold, t_hot, t_cold)
        m.record(
            "y_factor", voltage=v, y_factor=hot - cold, noise_temperature=temperature
        )
        if temperature < best:  # NaN where there is no contrast: never the best
            best, best_voltage = temperature, v

if math.isfinite(best):
    print(f"Tn {best:.1f} K at {best_voltage * 1e3:.3f} mV")
print(f"#{m.run.id} {m.run.status}: {m.run.path}")
