from thzdaq_instruments.sim.analyzers import SimNetworkAnalyzer, SimSpectrumAnalyzer
from thzdaq_instruments.sim.chopper import SimChopper
from thzdaq_instruments.sim.power_meter import SimPowerMeter
from thzdaq_instruments.sim.power_supply import SimPowerSupply, SimSupplyChannel
from thzdaq_instruments.sim.rotator import SimRotator
from thzdaq_instruments.sim.signal_generator import SimSignalGenerator
from thzdaq_instruments.sim.sis_block import (
    SimSisBiasChannel,
    SimSisBlock,
    SimSisCtrlChannel,
)
from thzdaq_instruments.sim.temperature import (
    SimTemperatureController,
    SimTemperatureInput,
)
from thzdaq_instruments.sim.vacuum import SimCompressor, SimVacuumGauge
from thzdaq_instruments.sim.yig_filter import SimYigChannel, SimYigFilter

SIMULATORS = {
    "sim.power_supply": (SimPowerSupply, "Simulated power supply"),
    "sim.signal_generator": (SimSignalGenerator, "Simulated signal generator"),
    "sim.power_meter": (SimPowerMeter, "Simulated power meter"),
    "sim.sis_block": (SimSisBlock, "Simulated SIS bias block"),
    "sim.yig_filter": (SimYigFilter, "Simulated YIG filter"),
    "sim.chopper": (SimChopper, "Simulated chopper"),
    "sim.temperature_controller": (
        SimTemperatureController,
        "Simulated temperature controller",
    ),
    "sim.spectrum_analyzer": (SimSpectrumAnalyzer, "Simulated spectrum analyzer"),
    "sim.network_analyzer": (SimNetworkAnalyzer, "Simulated network analyzer"),
    "sim.vacuum_gauge": (SimVacuumGauge, "Simulated vacuum gauge"),
    "sim.compressor": (SimCompressor, "Simulated compressor"),
    "sim.rotator": (SimRotator, "Simulated rotator"),
}


def register_simulators(registry) -> None:
    for key, (cls, title) in SIMULATORS.items():
        registry.register(key, cls, title=title, simulated=True)


__all__ = [
    "SIMULATORS",
    "SimChopper",
    "SimCompressor",
    "SimNetworkAnalyzer",
    "SimRotator",
    "SimSpectrumAnalyzer",
    "SimTemperatureController",
    "SimTemperatureInput",
    "SimVacuumGauge",
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
