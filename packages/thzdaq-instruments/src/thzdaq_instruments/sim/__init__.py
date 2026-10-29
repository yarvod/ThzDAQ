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

# Simulators as drivers of their own: class (with its driver_key), title
SIMULATORS = (
    (SimPowerSupply, "Simulated power supply"),
    (SimSignalGenerator, "Simulated signal generator"),
    (SimPowerMeter, "Simulated power meter"),
    (SimSisBlock, "Simulated SIS bias block"),
    (SimYigFilter, "Simulated YIG filter"),
    (SimChopper, "Simulated chopper"),
    (SimTemperatureController, "Simulated temperature controller"),
    (SimSpectrumAnalyzer, "Simulated spectrum analyzer"),
    (SimNetworkAnalyzer, "Simulated network analyzer"),
    (SimVacuumGauge, "Simulated vacuum gauge"),
    (SimCompressor, "Simulated compressor"),
    (SimRotator, "Simulated rotator"),
)


def register_simulators(registry) -> None:
    for cls, title in SIMULATORS:
        registry.register(cls.driver_key, cls, title=title, simulated=True)


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
