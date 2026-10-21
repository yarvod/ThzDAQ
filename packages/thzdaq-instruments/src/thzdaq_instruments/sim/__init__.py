from thzdaq_instruments.sim.chopper import SimChopper
from thzdaq_instruments.sim.power_meter import SimPowerMeter
from thzdaq_instruments.sim.power_supply import SimPowerSupply, SimSupplyChannel
from thzdaq_instruments.sim.signal_generator import SimSignalGenerator
from thzdaq_instruments.sim.sis_block import (
    SimSisBiasChannel,
    SimSisBlock,
    SimSisCtrlChannel,
)
from thzdaq_instruments.sim.yig_filter import SimYigChannel, SimYigFilter

SIMULATORS = {
    "sim.power_supply": (SimPowerSupply, "Simulated power supply"),
    "sim.signal_generator": (SimSignalGenerator, "Simulated signal generator"),
    "sim.power_meter": (SimPowerMeter, "Simulated power meter"),
    "sim.sis_block": (SimSisBlock, "Simulated SIS bias block"),
    "sim.yig_filter": (SimYigFilter, "Simulated YIG filter"),
    "sim.chopper": (SimChopper, "Simulated chopper"),
}


def register_simulators(registry) -> None:
    for key, (cls, title) in SIMULATORS.items():
        registry.register(key, cls, title=title, simulated=True)


__all__ = [
    "SIMULATORS",
    "SimChopper",
    "SimPowerMeter",
    "SimPowerSupply",
    "SimSignalGenerator",
    "SimSisBiasChannel",
    "SimSisBlock",
    "SimSisCtrlChannel",
    "SimSupplyChannel",
    "SimYigChannel",
    "SimYigFilter",
    "register_simulators",
]
