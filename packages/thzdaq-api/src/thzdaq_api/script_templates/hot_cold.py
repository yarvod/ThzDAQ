"""Hot/cold P-V: Y-factor and noise temperature against bias.

IF power against bias on the hot and the cold load: the chopper turns to
each load in turn and the bias is swept on each. The table "pv" holds both
sweeps, "y_factor" what follows from them. The bias goes back and the cold
load is set however the script ends. Needs the analysis package
(thzdaq[analysis]; the program has it).
"""

import math

from thzdaq import connect
from thzdaq_analysis.noise import match_hot_cold, noise_temperature

BIAS = "sis_bias_1"
DETECTOR = "power_meter_1"
LOAD = "chopper_1"  # turns to the hot or the cold load
VOLTAGE = "0:7:351"  # mV: start:stop:points
T_HOT, T_COLD = 300.0, 77.0  # K
LOAD_SETTLE_S = 2.0  # after the load turns
SETTLE_S = 0.01  # after each bias step

lab = connect()
bias, detector, load = lab[BIAS], lab[DETECTOR], lab[LOAD]

with lab.measurement(
    "pv_hot_cold",
    devices=[bias, detector, load],
    exclusive=[bias],
    parameters={"voltage": f"{VOLTAGE} mV", "t_hot": T_HOT, "t_cold": T_COLD},
) as m:
    m.plot("pv", x="voltage", y="power", group_by=("load",), title="P-V")
    m.plot("y_factor", x="voltage", y="noise_temperature", title="Tn-V")
    m.restore(bias, "voltage_set")
    m.on_exit(load, "to_cold")  # the daemon turns to the cold load at the end
    sweeps = {}
    for state in ("hot", "cold"):
        getattr(load, f"to_{state}")()
        m.sleep(LOAD_SETTLE_S)
        points = []
        for voltage in m.sweep(VOLTAGE, unit="mV"):
            bias.voltage_set = voltage
            m.sleep(SETTLE_S)
            reading = bias.read()
            power = detector.power
            m.record(
                "pv",
                load=state,
                voltage_set=voltage,
                voltage=reading.voltage,
                current=reading.current,
                power=power,
            )
            points.append((reading.voltage, power))
            m.progress()
        sweeps[state] = points
    best = math.inf
    for voltage, hot, cold in match_hot_cold(sweeps["hot"], sweeps["cold"]):
        tn = noise_temperature(hot, cold, T_HOT, T_COLD)
        m.record("y_factor", voltage=voltage, y_factor=hot - cold, noise_temperature=tn)
        if tn < best:  # NaN where there is no contrast: never the best
            best, best_voltage = tn, voltage

if math.isfinite(best):
    print(f"Tn {best:.1f} K at {best_voltage * 1e3:.3f} mV")
print(f"#{m.run.id} {m.run.status}: {m.run.path}")
