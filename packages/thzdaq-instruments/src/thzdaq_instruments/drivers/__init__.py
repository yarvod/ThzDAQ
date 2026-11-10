from thzdaq_instruments.drivers.agilent import AgilentE8247C
from thzdaq_instruments.drivers.arduino import ArduinoGrid
from thzdaq_instruments.drivers.chopper import ModbusChopper
from thzdaq_instruments.drivers.generic import GenericScpi
from thzdaq_instruments.drivers.keithley import Keithley2200
from thzdaq_instruments.drivers.lakeshore import (
    HeaterOutput,
    LakeShore336,
    TemperatureInput,
)
from thzdaq_instruments.drivers.national_instruments import NiYigFilter, YigChannel

# Pfeiffer (drivers/pfeiffer.py) is disabled: not used on the bench, to be rewritten
from thzdaq_instruments.drivers.power_supply import ScpiPowerSupply, SupplyChannel
from thzdaq_instruments.drivers.rigol import RigolDP832A
from thzdaq_instruments.drivers.rohde_schwarz import (
    RohdeSchwarzFSEK30,
    RohdeSchwarzHMP2030,
    RohdeSchwarzNRX,
    RohdeSchwarzZVA67,
)
from thzdaq_instruments.drivers.scontel import (
    ScontelSisBlock,
    SisBiasChannel,
    SisCtrlChannel,
)
from thzdaq_instruments.drivers.srs import StanfordSR830
from thzdaq_instruments.drivers.sumitomo import SumitomoF70, SumitomoF70Rest
from thzdaq_instruments.sim import (
    SimChopper,
    SimCompressor,
    SimGenericScpi,
    SimNetworkAnalyzer,
    SimPowerMeter,
    SimPowerSupply,
    SimRotator,
    SimSignalGenerator,
    SimSisBlock,
    SimSpectrumAnalyzer,
    SimTemperatureController,
    SimYigFilter,
)

# Built-in drivers: class (with its driver_key), title, simulator
DRIVERS = (
    (RigolDP832A, "Rigol DP832A power supply", SimPowerSupply),
    (RohdeSchwarzHMP2030, "R&S HMP2030 power supply", SimPowerSupply),
    (Keithley2200, "Keithley 2200 power supply", SimPowerSupply),
    (AgilentE8247C, "Agilent E8247C signal generator", SimSignalGenerator),
    (RohdeSchwarzNRX, "R&S NRX power meter", SimPowerMeter),
    (ScontelSisBlock, "Scontel SIS bias block", SimSisBlock),
    (NiYigFilter, "NI digital YIG filters", SimYigFilter),
    (ModbusChopper, "Modbus chopper", SimChopper),
    (RohdeSchwarzZVA67, "R&S ZVA67 network analyzer", SimNetworkAnalyzer),
    (RohdeSchwarzFSEK30, "R&S FSEK30 spectrum analyzer", SimSpectrumAnalyzer),
    (LakeShore336, "LakeShore 336 temperature controller", SimTemperatureController),
    (StanfordSR830, "SRS SR830 lock-in amplifier", None),
    (SumitomoF70, "Sumitomo F-70 compressor (RS-232)", SimCompressor),
    (SumitomoF70Rest, "Sumitomo F-70 compressor (REST)", SimCompressor),
    (ArduinoGrid, "Arduino wire grid rotator", SimRotator),
    (GenericScpi, "Generic instrument: text commands (SCPI)", SimGenericScpi),
)


def register_drivers(registry) -> None:
    for cls, title, sim in DRIVERS:
        registry.register(cls.driver_key, cls, title=title, sim=sim)


__all__ = [
    "DRIVERS",
    "AgilentE8247C",
    "ArduinoGrid",
    "GenericScpi",
    "HeaterOutput",
    "LakeShore336",
    "RohdeSchwarzFSEK30",
    "RohdeSchwarzZVA67",
    "StanfordSR830",
    "SumitomoF70",
    "SumitomoF70Rest",
    "TemperatureInput",
    "Keithley2200",
    "ModbusChopper",
    "NiYigFilter",
    "RigolDP832A",
    "RohdeSchwarzHMP2030",
    "RohdeSchwarzNRX",
    "ScontelSisBlock",
    "ScpiPowerSupply",
    "SisBiasChannel",
    "SisCtrlChannel",
    "SupplyChannel",
    "YigChannel",
    "register_drivers",
]
