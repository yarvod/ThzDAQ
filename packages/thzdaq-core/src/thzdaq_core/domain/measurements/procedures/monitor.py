"""Readings of any devices over time (P-t, T-t, SIS bias, vacuum, compressor).

What is read is chosen per device: "power_meter_1" reads its measured values
(power, temperature, voltage and current, ...), "sis_bias_1/voltage" one of
them. Every value is a row of the samples table (time, device, quantity,
value) and goes to the graph of its unit: dBm to P-t, K to T-t, V to V-t, ...
"""

from typing import Any, Dict, Iterable, List, Sequence

from thzdaq_api.leases import READ
from thzdaq_api.procedures import (
    COIL_PLOT,
    MONITOR_TIME,
    OTHER_PLOT,
    UNIT_PLOTS,
    default_quantities,
    monitor_quantities,
    plot_for,
    split_entry,
)
from thzdaq_instruments.quantities import Quantity, quantities_of, read_values
from thzdaq_instruments.units import GHZ, MA, MV, UA

from thzdaq_core.domain.measurements.procedures.common import (
    COIL_CURRENT_MA,
    CURRENT_UA,
    FREQUENCY_GHZ,
    POWER_DBM,
    VOLTAGE_MV,
)
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.parameters import FloatParameter, StringListParameter
from thzdaq_api.measurements import PlotInfo
from thzdaq_core.domain.measurements.procedure import Procedure


def _time_plot(title, y_label, y_scale=1.0) -> PlotInfo:
    return PlotInfo(
        title, title, "samples", "time", "value", x_label="Time, s",
        y_label=y_label, y_scale=y_scale, group_by=("device", "quantity"),
        where=(("plot", title),),
    )  # fmt: skip


class Monitor(Procedure):
    name = MONITOR_TIME
    title = "Monitor over time"
    description = (
        "Read the chosen values of devices (power, temperature, bias, pressure, "
        "compressor) at a fixed interval until stopped or the duration ends."
    )
    plots = (
        _time_plot(UNIT_PLOTS["dBm"], POWER_DBM),
        _time_plot(UNIT_PLOTS["K"], "Temperature, K"),
        _time_plot(UNIT_PLOTS["V"], VOLTAGE_MV, MV),
        _time_plot(UNIT_PLOTS["A"], CURRENT_UA, UA),
        _time_plot(COIL_PLOT, COIL_CURRENT_MA, MA),
        _time_plot(UNIT_PLOTS["Pa"], "Pressure, Pa"),
        _time_plot(UNIT_PLOTS["Hz"], FREQUENCY_GHZ, GHZ),
        _time_plot(OTHER_PLOT, "Value"),
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

    def slot_mode(self, slot: str) -> str:
        return READ  # watches, never sets

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
        started = ctx.monotonic()
        while True:
            ctx.check_cancel()
            elapsed = ctx.monotonic() - started
            stamp = ctx.now()
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
            ctx.sleep(max(0.0, next_tick - ctx.monotonic()))
