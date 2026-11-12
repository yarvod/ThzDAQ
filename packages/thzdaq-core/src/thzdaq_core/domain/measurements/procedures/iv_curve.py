from thzdaq_api.leases import EXCLUSIVE
from thzdaq_api.procedures import CURRENT_VS_COIL_CURRENT, CURRENT_VS_VOLTAGE
from thzdaq_instruments.capabilities import VoltageCurrentMeter, VoltageSource
from thzdaq_instruments.units import MV, UA

from thzdaq_core.domain.measurements.procedures.common import (
    IV_CAPTION,
    CURRENT_UA,
    VOLTAGE_MV,
    BiasVoltage,
    FirstPointDelay,
    SettleTime,
)
from thzdaq_api.measurements import PlotInfo
from thzdaq_core.domain.measurements.procedure import Procedure


class IVCurve(Procedure):
    name = CURRENT_VS_VOLTAGE
    slot_modes = {"bias": EXCLUSIVE}
    title = "SIS I-V curve"
    description = "Sweep the bias voltage and read voltage and current."
    guide = (
        "The first look at a junction and the check before any other SIS "
        "measurement. Unpumped (LO off) it shows the gap, the normal-state "
        "resistance Rn and the subgap leakage; with the LO on, the photon steps "
        "below the gap tell how strongly the mixer is pumped. Sweep from 0 up to "
        "above the gap (the default 0:7:351 mV) and stay within the range "
        "describe_device gives for the bias. A Josephson peak near zero bias means "
        f"the coil does not suppress it yet ({CURRENT_VS_COIL_CURRENT}). The plot's "
        "I-V analysis gives Rn and the gap."
    )
    requires = {"bias": (VoltageSource, VoltageCurrentMeter)}
    plots = (
        PlotInfo(
            key="iv",
            title="I-V",
            table="iv",
            x="voltage",
            y="current",
            x_label=VOLTAGE_MV,
            y_label=CURRENT_UA,
            x_scale=MV,
            y_scale=UA,
            analysis="iv",
            caption=IV_CAPTION,
        ),
    )

    voltage = BiasVoltage((0.0, 7e-3, 351))
    settle_time = SettleTime(0.01, maximum=10)
    first_point_delay = FirstPointDelay(0.5, maximum=10)

    def estimate_steps(self) -> int:
        return self.voltage.points

    def run(self, ctx) -> None:
        bias = ctx["bias"]
        initial = bias.get_voltage()
        ctx.on_exit(lambda: bias.set_voltage(initial))
        for index, voltage in enumerate(self.voltage.values()):
            ctx.check_cancel()
            bias.set_voltage(voltage)
            ctx.sleep(self.first_point_delay if index == 0 else self.settle_time)
            reading = bias.measure()
            ctx.record(
                "iv",
                voltage_set=voltage,
                voltage=reading.voltage,
                current=reading.current,
            )
            ctx.progress()
