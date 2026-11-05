"""I-V curve and analysis: a built-in procedure, then your numbers.

Runs the SIS I-V curve as its dock would (sis.iv_curve), waits for it and
works on its table here: the normal resistance from a line fitted above the
gap, the gap voltage where the current rises fastest. Put your analysis in
their place; the measurement keeps its data either way.
"""

import numpy as np

from thzdaq import connect

BIAS = "sis_bias_1"
VOLTAGE = "0:7:351"  # mV: start:stop:points
ABOVE_GAP_MV = 4.0  # the normal resistance is fitted above this bias

lab = connect()
run = lab.run("sis.iv_curve", bias=lab[BIAS], voltage=VOLTAGE)
print(f"#{run.id} {run.info.title} started")
ended = run.wait(progress=False)
if ended.status != "completed":
    raise SystemExit(f"#{run.id} {ended.status}: {ended.error or 'no analysis'}")

iv = run.table("iv")
voltage = np.asarray(iv["voltage"], dtype=float)  # V
current = np.asarray(iv["current"], dtype=float)  # A
above = voltage > ABOVE_GAP_MV * 1e-3
slope, _ = np.polyfit(voltage[above], current[above], 1)
rise = np.gradient(current, voltage)
gap = voltage[int(np.nanargmax(rise))]

print(f"Rn = {1 / slope:.2f} Ohm (above {ABOVE_GAP_MV} mV)")
print(f"Vgap = {gap * 1e3:.3f} mV")
print(f"#{run.id}: {ended.path}")
