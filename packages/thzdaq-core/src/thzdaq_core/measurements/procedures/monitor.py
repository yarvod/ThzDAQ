"""Readings of any devices over time (P-t, T-t, SIS bias, vacuum, compressor).

What is read is chosen per device: "power_meter_1" reads its measured values
(power, temperature, voltage and current, ...), "sis_bias_1/voltage" one of
them. Every value is a row of the samples table (time, device, quantity,
value) and goes to the graph of its unit: dBm to P-t, K to T-t, V to V-t, ...
"""

import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from thzdaq_instruments.quantities import Quantity, quantities_of, read_values
from thzdaq_instruments.units import GHZ, MA, MV, UA

from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.parameters import FloatParameter, StringListParameter
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.registry import register_procedure

KEY_SEPARATOR = "/"


def monitor_quantities(quantities: Iterable[Quantity]) -> List[Quantity]:
    """Quantities worth watching: numeric readings, not configuration."""
    return [
        q
        for q in quantities
        if q.readable and q.kind in ("float", "int") and not q.persistent
    ]


def default_quantities(quantities: Iterable[Quantity]) -> List[Quantity]:
    """Read when a device is watched without a choice: measured values with a
    unit, or the readable setpoints when nothing is measured (a SIS coil
    current). A value without a unit (the NRX reading in its display unit) can
    be chosen by hand."""
    candidates = [q for q in monitor_quantities(quantities) if q.unit]
    return [q for q in candidates if not q.settable] or candidates


def plot_for(quantity: Quantity) -> str:
    """The time graph of a quantity, by its unit."""
    if quantity.unit == "A" and quantity.key in ("current_set", "coil_current"):
        return "Coil-t"  # mA of a coil, not the µA of a SIS on I-t
    return UNIT_PLOTS.get(quantity.unit, "Value-t")


UNIT_PLOTS = {
    "dBm": "P-t",
    "K": "T-t",
    "V": "V-t",
    "A": "I-t",
    "Pa": "p-t",
    "Hz": "f-t",
}


def split_entry(entry: str) -> Tuple[str, Optional[str]]:
    """ "sis_bias_1/voltage" -> ("sis_bias_1", "voltage"); "power_meter_1" -> (ref, None)."""
    ref, _, key = entry.partition(KEY_SEPARATOR)
    return ref, key or None


def _time_plot(title, y_label, y_scale=1.0) -> PlotSpec:
    return PlotSpec(
        title, title, "samples", "time", "value", x_label="Time, s",
        y_label=y_label, y_scale=y_scale, group_by=("device", "quantity"),
        where=(("plot", title),),
    )  # fmt: skip


@register_procedure
class Monitor(Procedure):
    name = "monitor.time"
    title = "Monitor over time"
    description = (
        "Read the chosen values of devices (power, temperature, bias, pressure, "
        "compressor) at a fixed interval until stopped or the duration ends."
    )
    plots = (
        _time_plot("P-t", "Power, dBm"),
        _time_plot("T-t", "Temperature, K"),
        _time_plot("V-t", "Voltage, mV", MV),
        _time_plot("I-t", "Current, μA", UA),
        _time_plot("Coil-t", "Coil current, mA", MA),
        _time_plot("p-t", "Pressure, Pa"),
        _time_plot("f-t", "Frequency, GHz", GHZ),
        _time_plot("Value-t", "Value"),
    )

    watch = StringListParameter(
        "Devices",
        default=("detector",),
        help="Device refs, or ref/quantity to read one value of a device",
    )
    interval = FloatParameter("Interval", default=1.0, minimum=0.01, unit="s")
    duration = FloatParameter(
        "Duration", default=0.0, minimum=0, unit="s", help="0: until stopped"
    )
    window = FloatParameter(
        "Plot window",
        default=600.0,
        minimum=0,
        unit="s",
        help="Graphs show the last part of the curves, so a long monitor stays "
        "fast; the data keeps every sample. 0: show everything",
    )

    def refs(self) -> List[str]:
        refs: List[str] = []
        for entry in self.watch:
            ref, _ = split_entry(entry)
            if ref not in refs:
                refs.append(ref)
        return refs

    def slots(self):
        return {ref: object for ref in self.refs()}

    def estimate_steps(self):
        return int(self.duration / self.interval) + 1 if self.duration else None

    def plot_window(self):
        return self.window or None

    def active_plots(self, quantities=None):
        """The graphs of the units of the chosen values (P-t for dBm, ...)."""
        if quantities is None:
            return self.plots
        titles = set()
        for ref in self.refs():
            try:
                titles.update(plot_for(q) for q in self.choose(ref, quantities(ref)))
            except ProcedureError:
                continue
        return tuple(p for p in self.plots if p.title in titles)

    def chosen(self, ref: str, device: Any) -> List[Quantity]:
        return self.choose(ref, quantities_of(device))

    def choose(self, ref: str, quantities: Iterable[Quantity]) -> List[Quantity]:
        available = monitor_quantities(quantities)
        keys = [key for r, key in map(split_entry, self.watch) if r == ref and key]
        if not keys:
            return default_quantities(available)
        by_key = {q.key: q for q in available}
        unknown = [key for key in keys if key not in by_key]
        if unknown:
            raise ProcedureError(f"{ref} has no readable {', '.join(unknown)}")
        return [by_key[key] for key in keys]

    def run(self, ctx) -> None:
        devices = {ref: ctx[ref] for ref in self.refs()}
        titles = {ref: use.title or ref for ref, use in ctx.measurement.devices.items()}
        chosen: Dict[str, Sequence[Quantity]] = {
            ref: self.chosen(ref, device) for ref, device in devices.items()
        }
        started = time.monotonic()
        while True:
            ctx.check_cancel()
            elapsed = time.monotonic() - started
            stamp = datetime.now().isoformat(timespec="milliseconds")
            for ref, device in devices.items():
                values = read_values(device, chosen[ref])
                for quantity in chosen[ref]:
                    ctx.record(
                        "samples",
                        time=elapsed,
                        wall_time=stamp,
                        device=titles.get(ref, ref),
                        quantity=quantity.title,
                        key=quantity.key,
                        value=values.get(quantity.key),
                        unit=quantity.unit,
                        plot=plot_for(quantity),
                    )
            ctx.progress()
            if self.duration and elapsed + self.interval > self.duration:
                return
            next_tick = started + ctx.done * self.interval
            ctx.sleep(max(0.0, next_tick - time.monotonic()))
