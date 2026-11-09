"""Bias sweep: I-V and P-V of a SIS junction.

The SIS bias goes over a range, each point a record of the table "iv";
I-V and P-V are drawn as it runs. The bias goes back to where it was
however the measurement ends, Stop too.
"""

from thzdaq import connect, device, plot, value

bias = device("SIS bias", kind="sis_bias")  # the device swept
detector = device("Detector", "PowerDetector")  # read at each point
voltage = value("Bias voltage", "0:7:351", unit="mV")
settle = value("Settle", 10, unit="ms", help="after each step")
iv = plot("I-V", table="iv", x="voltage", y="current")
pv = plot("P-V", table="iv", x="voltage", y="power")

lab = connect()
with lab.measurement(
    "bias_sweep",
    devices=[bias, detector],
    exclusive=[bias],  # another's change of the bias would spoil the data
    total=voltage.points,
) as m:
    m.restore(bias, "voltage_set")  # the daemon sets it back at the end
    for v in m.sweep(voltage):  # each step looks for a Stop
        bias.voltage_set = v
        m.sleep(settle)
        reading = bias.read()  # voltage and current in one read
        m.record(
            "iv",
            voltage_set=v,
            voltage=reading.voltage,
            current=reading.current,
            power=detector.power,
        )
        m.progress()

print(f"#{m.run.id} {m.run.status}: {m.run.path}")
