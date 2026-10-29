"""What a SIS bias block is, for its driver and its simulator: four DEV channels,
each configured as a SIS bias or a SIS coil."""

from typing import Dict

from thzdaq_instruments.instrument import SubdeviceType

DEVICES = ("DEV1", "DEV2", "DEV3", "DEV4")


def parts(bias_part: type, coil_part: type) -> Dict[str, SubdeviceType]:
    """The configurable parts, with the classes the driver (or simulator) returns."""
    return {
        "sis_bias": SubdeviceType("SIS bias", "channel", DEVICES, bias_part),
        "sis_coil": SubdeviceType("SIS coil", "ctrl", DEVICES, coil_part),
    }
