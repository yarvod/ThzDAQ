"""I-V curve and analysis: a built-in procedure, then your numbers.

Runs the SIS I-V curve as its dock would (sis.current_vs_voltage), waits for it and
works on its table here: the normal resistance from a line fitted above the
gap, the gap voltage where the current rises fastest. Put your analysis in
their place; the measurement keeps its data either way.
"""

import numpy as np

from thzdaq import connect, device, value

bias = device("SIS bias", kind="sis_bias")
voltage = value("Bias voltage", "0:7:351", unit="mV")
above_gap = value("Fit above", 4, unit="mV", help="Rn is fitted above this bias")

lab = connect()
run = lab.run("sis.current_vs_voltage", bias=bias, voltage=voltage)
print(f"#{run.id} {run.info.title} started")
ended = run.wait(progress=False)
if ended.status != "completed":
    raise SystemExit(f"#{run.id} {ended.status}: {ended.error or 'no analysis'}")

iv = run.table("iv")
measured = np.asarray(iv["voltage"], dtype=float)  # V
current = np.asarray(iv["current"], dtype=float)  # A
above = measured > above_gap
slope, _ = np.polyfit(measured[above], current[above], 1)
rise = np.gradient(current, measured)
gap = measured[int(np.nanargmax(rise))]

print(f"Rn = {1 / slope:.2f} Ohm (above {above_gap * 1e3:g} mV)")
print(f"Vgap = {gap * 1e3:.3f} mV")
print(f"#{run.id}: {ended.path}")
