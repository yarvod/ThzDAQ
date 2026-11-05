"""Bias sweep: I-V and P-V of a SIS junction.

The SIS bias goes over a range, each point a record of the table "iv";
I-V and P-V are drawn as it runs. The bias goes back to where it was
however the script ends, Stop too.
"""

from thzdaq import connect

BIAS = "sis_bias_1"  # the device swept
DETECTOR = "power_meter_1"  # read at each point
VOLTAGE = "0:7:351"  # mV: start:stop:points
SETTLE_S = 0.01  # after each step

lab = connect()
bias, detector = lab[BIAS], lab[DETECTOR]

with lab.measurement(
    "bias_sweep",
    devices=[bias, detector],
    exclusive=[bias],  # another's change of the bias would spoil the data
    parameters={"voltage": f"{VOLTAGE} mV", "settle": SETTLE_S},
) as m:
    m.plot("iv", x="voltage", y="current", title="I-V")
    m.plot("iv", x="voltage", y="power", title="P-V")
    m.restore(bias, "voltage_set")  # the daemon sets it back at the end
    for voltage in m.sweep(VOLTAGE, unit="mV"):  # each step looks for a Stop
        bias.voltage_set = voltage
        m.sleep(SETTLE_S)
        reading = bias.read()  # voltage and current in one read
        m.record(
            "iv",
            voltage_set=voltage,
            voltage=reading.voltage,
            current=reading.current,
            power=detector.power,
        )
        m.progress()

print(f"#{m.run.id} {m.run.status}: {m.run.path}")
