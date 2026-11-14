"""Hot/cold P-V over the grid's angles: Y-factor and Tn at each angle.

At each angle of the wire grid the chopper turns to the hot and the cold
load and the bias is swept on each, as in hot_cold. The table "pv" holds
every sweep with its angle and load, "y_factor" what follows at each angle.
The bias and the grid go back and the cold load is set however the
measurement ends. Needs the analysis package (thzdaq[analysis]; the program
has it).
"""

from thzdaq import connect, device, plot, value
from thzdaq_analysis.noise import match_hot_cold, noise_temperature

bias = device("SIS bias", kind="sis_bias")
detector = device("Detector", "PowerDetector")
load = device("Load", "LoadSwitch")  # turns to the hot or the cold load
grid = device("Grid", "Rotator")
voltage = value("Bias voltage", "0:7:351", unit="mV")
angle = value("Grid angle", "0:90:10", unit="deg")
t_hot = value("Hot load", 300, unit="K")
t_cold = value("Cold load", 77, unit="K")
grid_settle = value("Grid settle", 1, unit="s", help="after the grid turns")
load_settle = value("Load settle", 2, unit="s", help="after the load turns")
settle = value("Settle", 10, unit="ms", help="after each bias step")
pv = plot("P-V", table="pv", x="voltage", y="power", group_by=("angle", "load"))
tn = plot(
    "Tn-V", table="y_factor", x="voltage", y="noise_temperature", group_by="angle"
)

lab = connect()
with lab.measurement(
    "pv_hot_cold_grid",
    devices=[bias, detector, load, grid],
    exclusive=[bias, grid],
    total=angle.points * 2 * voltage.points,
) as m:
    m.restore(bias, "voltage_set")
    m.restore(grid, "angle")
    m.on_exit(load, "to_cold")  # the daemon turns to the cold load at the end
    for a in m.sweep(angle):
        grid.angle = a
        m.sleep(grid_settle)
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
                    angle=a,
                    load=state,
                    voltage_set=v,
                    voltage=reading.voltage,
                    current=reading.current,
                    power=power,
                )
                points.append((reading.voltage, power))
                m.progress()
            sweeps[state] = points
        for v, hot, cold in match_hot_cold(sweeps["hot"], sweeps["cold"]):
            m.record(
                "y_factor",
                angle=a,
                voltage=v,
                y_factor=hot - cold,
                noise_temperature=noise_temperature(hot, cold, t_hot, t_cold),
            )

print(f"#{m.run.id} {m.run.status}: {m.run.path}")
