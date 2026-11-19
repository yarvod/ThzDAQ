"""What each class of the registry can do: drivers, their channels and
sub-device parts, simulators. The table was written down from the classes as
they were before capabilities were declared by inheritance; a change in it is
a change of what a device offers to measurements, docks and the guard."""

import pytest
from thzdaq_instruments import default_registry
from thzdaq_instruments.capabilities import PowerDetector, capabilities_of
from thzdaq_instruments.instrument import Instrument

CAPABILITIES = {
    "RigolDP832A": {"Identifiable", "RawCommands"},
    "RigolChannel": {
        "CurrentSource", "OutputProtection", "Switchable", "VoltageCurrentMeter",
        "VoltageSource",
    },
    "RohdeSchwarzHMP2030": {"Identifiable", "RawCommands"},
    "SupplyChannel": {
        "CurrentSource", "Switchable", "VoltageCurrentMeter", "VoltageSource",
    },
    "Keithley2200": {"Identifiable", "RawCommands"},
    "AgilentE8247C": {
        "FrequencySource", "Identifiable", "PowerLevel", "RawCommands", "Switchable",
    },
    "RohdeSchwarzNRX": {"Identifiable", "PowerDetector", "RawCommands"},
    "KeysightU2002H": {"Identifiable", "PowerDetector", "RawCommands"},
    "ScontelSisBlock": {"Identifiable", "RawCommands"},
    "SisBiasChannel": {"PreciseVoltageSource", "VoltageCurrentMeter", "VoltageSource"},
    "SisCtrlChannel": {"CurrentSource"},
    "NiYigFilter": {"Identifiable"},
    "YigChannel": {"TunableFilter"},
    "ModbusChopper": {"Identifiable", "LoadSwitch"},
    "RohdeSchwarzZVA67": {
        "Identifiable", "NetworkAnalyzer", "PowerLevel", "RawCommands",
    },
    "RohdeSchwarzFSEK30": {"Identifiable", "RawCommands", "SpectrumAnalyzer"},
    "LakeShore336": {"Identifiable", "RawCommands"},
    "TemperatureInput": {"Thermometer"},
    "StanfordSR830": {"Identifiable", "RawCommands"},
    "SumitomoF70": {"Compressor", "Identifiable", "RawCommands"},
    "SumitomoF70Rest": {"Compressor", "Identifiable"},
    "ArduinoGrid": {"Identifiable", "Rotator"},
    "GenericScpi": {"Identifiable", "RawCommands"},
    "SimPowerSupply": {"Identifiable", "RawCommands"},
    # The supply simulator of drivers whose outputs have no protection (0.3)
    "SimPlainPowerSupply": {"Identifiable", "RawCommands"},
    "SimSingleSupply": {"Identifiable", "RawCommands"},
    "SimPlainSupplyChannel": {
        "CurrentSource", "Switchable", "VoltageCurrentMeter", "VoltageSource",
    },
    "SimSupplyChannel": {
        "CurrentSource", "OutputProtection", "Switchable", "VoltageCurrentMeter",
        "VoltageSource",
    },
    "SimSignalGenerator": {
        "FrequencySource", "Identifiable", "PowerLevel", "RawCommands", "Switchable",
    },
    "SimPowerMeter": {"Identifiable", "PowerDetector", "RawCommands"},
    "SimU2000": {"Identifiable", "PowerDetector", "RawCommands"},
    "SimSisBlock": {"Identifiable", "RawCommands"},
    "SimSisBiasChannel": {"PreciseVoltageSource", "VoltageCurrentMeter", "VoltageSource"},
    "SimSisCtrlChannel": {"CurrentSource"},
    "SimYigFilter": {"Identifiable", "RawCommands"},
    "SimYigChannel": {"TunableFilter"},
    "SimChopper": {"Identifiable", "LoadSwitch", "RawCommands"},
    "SimTemperatureController": {"Identifiable", "RawCommands"},
    "SimTemperatureInput": {"Thermometer"},
    "SimSpectrumAnalyzer": {"Identifiable", "RawCommands", "SpectrumAnalyzer"},
    "SimNetworkAnalyzer": {
        "Identifiable", "NetworkAnalyzer", "PowerLevel", "RawCommands",
    },
    "SimVacuumGauge": {"Identifiable", "RawCommands", "VacuumGauge"},
    "SimCompressor": {"Compressor", "Identifiable", "RawCommands"},
    "SimRotator": {"Identifiable", "RawCommands", "Rotator"},
    "SimGenericScpi": {"Identifiable", "RawCommands"},
}  # fmt: skip


def registry_classes():
    """Every class the default registry reaches, once."""
    found = {}
    for info in default_registry().all():
        for instrument in filter(None, (info.cls, info.sim)):
            parts = (instrument, instrument.channel_class) + tuple(
                sub.part_class for sub in instrument.subdevices.values()
            )
            for cls in parts:
                if cls is not None:
                    found.setdefault(cls.__name__, cls)
    return found


def test_the_table_names_every_class_of_the_registry():
    assert set(registry_classes()) == set(CAPABILITIES)


@pytest.mark.parametrize("name", sorted(CAPABILITIES))
def test_capabilities_of_each_class(name):
    cls = registry_classes()[name]
    assert {c.__name__ for c in capabilities_of(cls)} == CAPABILITIES[name]


class Sensor(Instrument):
    """A power sensor with a frequency of its own (the one its correction is for)."""

    def set_frequency(self, frequency: float) -> None:
        self.frequency = frequency

    def get_frequency(self) -> float:
        return self.frequency


def test_a_matching_method_name_is_no_capability():
    assert capabilities_of(Sensor) == ()


def test_a_declared_capability_without_its_method_fails_as_it_is_made():
    class HalfDetector(Instrument, PowerDetector):
        pass

    with pytest.raises(TypeError, match="read_power"):
        HalfDetector()
