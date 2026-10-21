from thzdaq_instruments.drivers.agilent import AgilentE8247C
from thzdaq_instruments.drivers.chopper import ModbusChopper
from thzdaq_instruments.drivers.keithley import Keithley2200
from thzdaq_instruments.drivers.national_instruments import NiYigFilter, YigChannel
from thzdaq_instruments.drivers.power_supply import ScpiPowerSupply, SupplyChannel
from thzdaq_instruments.drivers.rigol import RigolDP832A
from thzdaq_instruments.drivers.rohde_schwarz import (
    RohdeSchwarzHMP2030,
    RohdeSchwarzNRX,
)
from thzdaq_instruments.drivers.scontel import (
    ScontelSisBlock,
    SisBiasChannel,
    SisCtrlChannel,
)
from thzdaq_instruments.sim import (
    SimChopper,
    SimPowerMeter,
    SimPowerSupply,
    SimSignalGenerator,
    SimSisBlock,
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
}


def register_drivers(registry) -> None:
    for key, (cls, title, sim) in DRIVERS.items():
        registry.register(key, cls, title=title, sim=sim)


__all__ = [
    "DRIVERS",
    "AgilentE8247C",
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
