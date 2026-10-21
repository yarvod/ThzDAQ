from thzdaq_instruments.drivers.agilent import AgilentE8247C
from thzdaq_instruments.drivers.arduino import ArduinoGrid
from thzdaq_instruments.drivers.chopper import ModbusChopper
from thzdaq_instruments.drivers.keithley import Keithley2200
from thzdaq_instruments.drivers.lakeshore import (
    HeaterOutput,
    LakeShore336,
    TemperatureInput,
)
from thzdaq_instruments.drivers.national_instruments import NiYigFilter, YigChannel
from thzdaq_instruments.drivers.pfeiffer import (
    PfeifferDevice,
    PfeifferGauge,
    PfeifferTurboPump,
)
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
    SimNetworkAnalyzer,
    SimPowerMeter,
    SimPowerSupply,
    SimRotator,
    SimSignalGenerator,
    SimSisBlock,
    SimSpectrumAnalyzer,
    SimTemperatureController,
    SimVacuumGauge,
    SimYigFilter,
)

DRIVERS = {
    "rigol.dp832a": (RigolDP832A, "Rigol DP832A power supply", SimPowerSupply),
    "rs.hmp2030": (RohdeSchwarzHMP2030, "R&S HMP2030 power supply", SimPowerSupply),
    "keithley.2200": (Keithley2200, "Keithley 2200 power supply", SimPowerSupply),
    "agilent.e8247c": (
        AgilentE8247C,
        "Agilent E8247C signal generator",
        SimSignalGenerator,
    ),
    "rs.nrx": (RohdeSchwarzNRX, "R&S NRX power meter", SimPowerMeter),
    "scontel.sis_block": (ScontelSisBlock, "Scontel SIS bias block", SimSisBlock),
    "ni.yig": (NiYigFilter, "NI digital YIG filters", SimYigFilter),
    "chopper.modbus": (ModbusChopper, "Modbus chopper", SimChopper),
    "rs.zva67": (RohdeSchwarzZVA67, "R&S ZVA67 network analyzer", SimNetworkAnalyzer),
    "rs.fsek30": (
        RohdeSchwarzFSEK30,
        "R&S FSEK30 spectrum analyzer",
        SimSpectrumAnalyzer,
    ),
    "lakeshore.336": (
        LakeShore336,
        "LakeShore 336 temperature controller",
        SimTemperatureController,
    ),
    "srs.sr830": (StanfordSR830, "SRS SR830 lock-in amplifier", None),
    "sumitomo.f70": (SumitomoF70, "Sumitomo F-70 compressor (RS-232)", SimCompressor),
    "sumitomo.f70_rest": (
        SumitomoF70Rest,
        "Sumitomo F-70 compressor (REST)",
        SimCompressor,
    ),
    "pfeiffer.tc110": (PfeifferTurboPump, "Pfeiffer TC 110 turbo pump drive", None),
    "pfeiffer.gauge": (PfeifferGauge, "Pfeiffer active vacuum gauge", SimVacuumGauge),
    "arduino.grid": (ArduinoGrid, "Arduino wire grid rotator", SimRotator),
}


def register_drivers(registry) -> None:
    for key, (cls, title, sim) in DRIVERS.items():
        registry.register(key, cls, title=title, sim=sim)


__all__ = [
    "DRIVERS",
    "AgilentE8247C",
    "ArduinoGrid",
    "HeaterOutput",
    "LakeShore336",
    "PfeifferDevice",
    "PfeifferGauge",
    "PfeifferTurboPump",
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
