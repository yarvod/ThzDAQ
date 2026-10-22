"""Readings of any devices over time (P-t, T-t, SIS bias monitor, vacuum, compressor)."""

import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Tuple

from thzdaq_instruments.capabilities import (
    Compressor,
    CurrentSource,
    PowerDetector,
    Thermometer,
    VacuumGauge,
    VoltageCurrentMeter,
)
from thzdaq_instruments.units import MA, MV, UA

from thzdaq_core.measurements.parameters import FloatParameter, StringListParameter
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.registry import register_procedure

Reader = Callable[[Any], Dict[str, float]]


def _measure(port) -> Dict[str, float]:
    reading = port.measure()
    return {"voltage": reading.voltage, "current": reading.current}


def _compressor(port) -> Dict[str, float]:
    values = {f"temperature_{i}": t for i, t in enumerate(port.read_temperatures(), 1)}
    values.update({f"pressure_{i}": p for i, p in enumerate(port.read_pressures(), 1)})
    return values


# Capability -> what to read; first matching readers are combined
READERS: List[Tuple[type, Reader]] = [
    (PowerDetector, lambda port: {"power": port.read_power()}),
    (Thermometer, lambda port: {"temperature": port.read_temperature()}),
    (VoltageCurrentMeter, _measure),
    (VacuumGauge, lambda port: {"pressure": port.read_pressure()}),
    (Compressor, _compressor),
]


def readers_for(port) -> List[Reader]:
    found = [reader for capability, reader in READERS if isinstance(port, capability)]
    if not found and isinstance(port, CurrentSource):
        # e.g. a SIS coil: no meter, but the current readback is useful
        found.append(lambda p: {"coil_current": p.get_current()})
    return found


def read_port(port) -> Dict[str, float]:
    values: Dict[str, float] = {}
    for reader in readers_for(port):
        values.update(reader(port))
    return values


def _time_plot(key, title, y, y_label, y_scale=1.0) -> PlotSpec:
    return PlotSpec(
        key, title, "samples", "time", y,
        x_label="Time, s", y_label=y_label, y_scale=y_scale, group_by=("device",),
    )  # fmt: skip


@register_procedure
class Monitor(Procedure):
    name = "monitor.time"
    title = "Monitor over time"
    description = (
        "Read power, temperature, bias, pressure or compressor values of the "
        "chosen devices at a fixed interval until stopped or the duration ends."
    )
    plots = (
        _time_plot("power", "P-t", "power", "Power, dBm"),
        _time_plot("temperature", "T-t", "temperature", "Temperature, K"),
        _time_plot("voltage", "V-t", "voltage", "Voltage, mV", MV),
        _time_plot("current", "I-t", "current", "Current, μA", UA),
        _time_plot("coil", "Coil-t", "coil_current", "Coil current, mA", MA),
        _time_plot("pressure", "p-t", "pressure", "Pressure, Pa"),
    )

    watch = StringListParameter("Devices", default=("detector",))
    interval = FloatParameter("Interval", default=1.0, minimum=0.01, unit="s")
    duration = FloatParameter(
        "Duration", default=0.0, minimum=0, unit="s", help="0: until stopped"
    )

    def slots(self):
        return {ref: object for ref in self.watch}

    def estimate_steps(self):
        return int(self.duration / self.interval) + 1 if self.duration else None

    def run(self, ctx) -> None:
        devices = {ref: ctx[ref] for ref in self.watch}
        titles = {ref: use.title or ref for ref, use in ctx.measurement.devices.items()}
        started = time.monotonic()
        while True:
            ctx.check_cancel()
            elapsed = time.monotonic() - started
            stamp = datetime.now().isoformat(timespec="milliseconds")
            for ref, device in devices.items():
                ctx.record(
                    "samples",
                    time=elapsed,
                    wall_time=stamp,
                    device=titles.get(ref, ref),
                    **read_port(device),
                )
            ctx.progress()
            if self.duration and elapsed + self.interval > self.duration:
                return
            next_tick = started + (ctx.done) * self.interval
            ctx.sleep(max(0.0, next_tick - time.monotonic()))
