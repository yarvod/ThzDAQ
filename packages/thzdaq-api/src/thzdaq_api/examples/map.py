"""Map: IF power over the SIS bias and its coil current.

The coil current goes over a range; at each the bias is swept, a record of
the table "map" per point, drawn as a map as it goes. The bias and the coil
go back to where they were however the measurement ends.
"""

from thzdaq import connect, device, plot, value

bias = device("SIS bias", kind="sis_bias")
coil = device("SIS coil", kind="sis_coil")
detector = device("Detector", "PowerDetector")
voltage = value("Bias voltage", "0:7:71", unit="mV")
current = value("Coil current", "0:20:11", unit="mA")
settle = value("Settle", 10, unit="ms", help="after each step")
power = plot(
    "P(V, I coil)", table="map", x="voltage", y="coil_current", z="power",
    kind="map",
)  # fmt: skip

lab = connect()
with lab.measurement(
    "map",
    devices=[bias, coil, detector],
    exclusive=[bias, coil],
    total=voltage.points * current.points,
) as m:
    m.restore(bias, "voltage_set")
    m.restore(coil, "current_set")
    for i in m.sweep(current):
        coil.current_set = i
        m.sleep(settle)
        for v in m.sweep(voltage):
            bias.voltage_set = v
            m.sleep(settle)
            m.record(
                "map", coil_current=i, voltage=bias.read().voltage,
                power=detector.power,
            )  # fmt: skip
            m.progress()

print(f"#{m.run.id} {m.run.status}: {m.run.path}")
