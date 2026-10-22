"""Import device configs of the legacy app (settings.ini, [Configs]) into a station profile.

Legacy entries are per "device widget": every SIS config (bias DEV, coil DEV,
offsets, calibration) on one Scontel block was its own entry. Here a block is
one instrument and each config becomes a bias and a coil device on it.
"""

import re
from collections import OrderedDict
from typing import Any, Dict, List, Mapping, Optional, Tuple

from thzdaq_instruments.drivers import NiYigFilter, ScontelSisBlock, SumitomoF70Rest
from thzdaq_instruments.drivers.chopper import ModbusChopper
from thzdaq_instruments.drivers.rohde_schwarz import RohdeSchwarzNRX
from thzdaq_instruments.transport.base import (
    HTTP,
    PROLOGIX,
    PROLOGIX_USB,
    SERIAL,
    SOCKET,
    ConnectionSpec,
)

from thzdaq_core.errors import StationError
from thzdaq_core.station.kinds import instrument_type
from thzdaq_core.station.config import DeviceConfig, InstrumentConfig, StationConfig

LEGACY_DRIVERS = {
    "Keithley Power Supply": "keithley.2200",
    "Agilent Signal Generator": "agilent.e8247c",
    "Rigol Power Supply": "rigol.dp832a",
    "Sumitomo F70 Compressor": "sumitomo.f70_rest",
    "LakeShore Temperature Controller": "lakeshore.336",
    "Rohde Schwarz VNA ZVA 67": "rs.zva67",
    "Rohde Schwarz Spectrum FSEK 30": "rs.fsek30",
    "Rohde Schwarz Power Supply": "rs.hmp2030",
    "Scontel SIS Block": "scontel.sis_block",
    "GRID": "arduino.grid",
}
# Connection adapters, not instruments: their address is already in each device config
LEGACY_ADAPTER_SECTIONS = {"Prologix ethernet"}
LEGACY_KINDS = {
    "SOCKET": SOCKET,
    "SOCKET SINGLE": SOCKET,
    "PROLOGIX ETHERNET": PROLOGIX,
    "PROLOGIX USB": PROLOGIX_USB,
    "HTTP": HTTP,
    "SERIAL": SERIAL,
}


def slug(text: str) -> str:
    value = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    return value if value and not value[0].isdigit() else f"i_{value}"


def next_id(device_type: str, taken: Mapping[str, Any]) -> str:
    number = 1
    while f"{device_type}_{number}" in taken:
        number += 1
    return f"{device_type}_{number}"


def _offset(value: Any) -> float:
    # The legacy UI stored offsets as summed floats (-0.00020000000000000004)
    return round(float(value or 0), 12) + 0.0


def legacy_connection(entry: Mapping[str, Any], driver: str) -> ConnectionSpec:
    adapter = str(entry.get("adapter") or "SOCKET").upper()
    kind = LEGACY_KINDS.get(adapter)
    if kind is None:
        raise StationError(f"Unknown legacy adapter {adapter!r}")
    host = entry.get("host") or None
    port = int(entry["port"]) if str(entry.get("port") or "").isdigit() else None
    gpib = entry.get("gpib")
    if driver == "scontel.sis_block":
        return ScontelSisBlock.connection(host=host, port=port or 9876)
    if driver == "sumitomo.f70_rest":
        return SumitomoF70Rest.connection(host=host, port=port or 21024)
    if kind == HTTP:
        # The grid answers after the move, give it time
        timeout = 30.0 if driver == "arduino.grid" else 2.0
        return ConnectionSpec(HTTP, host=host, port=port, timeout=timeout)
    if kind == PROLOGIX:
        return ConnectionSpec(PROLOGIX, host=host, port=port, gpib=int(gpib))
    if kind == PROLOGIX_USB:
        serial_port = entry.get("port") or host
        return ConnectionSpec(
            PROLOGIX_USB, serial_port=str(serial_port), gpib=int(gpib)
        )
    if kind == SERIAL:
        return ConnectionSpec(SERIAL, serial_port=str(entry.get("port") or host))
    return ConnectionSpec(SOCKET, host=host, port=port)


def _entry_name(section: str, entry: Mapping[str, Any]) -> str:
    name = entry.get("name") or entry.get("_name") or section
    if name == section and entry.get("cid") is not None:
        name = f"{section} {entry['cid']}"
    return str(name)


def _state_defaults() -> Dict[str, InstrumentConfig]:
    """Instruments the legacy app addressed through hard-coded state constants."""
    return {
        "power_meter_1": InstrumentConfig(
            driver="rs.nrx",
            connection=RohdeSchwarzNRX.connection(),
            # The legacy driver configured the meter like this on every connect
            options={"aperture_time": 0.05, "averaging": False},
            title="R&S NRX",
        ),
        "yig_filter_1": InstrumentConfig(
            driver="ni.yig", connection=NiYigFilter.connection(), title="NI YIG"
        ),
        "chopper_1": InstrumentConfig(
            driver="chopper.modbus",
            connection=ModbusChopper.connection(),
            title="Chopper",
        ),
    }


def station_from_legacy(
    configs: Mapping[str, List[Mapping[str, Any]]],
    *,
    name: str = "legacy",
    include_state_defaults: bool = True,
) -> Tuple[StationConfig, List[str]]:
    """Returns the profile and notes about skipped or merged entries."""
    instruments: "OrderedDict[str, InstrumentConfig]" = OrderedDict()
    notes: List[str] = []
    sis_blocks: Dict[tuple, str] = {}
    sis_count = 0

    for section, entries in configs.items():
        if section in LEGACY_ADAPTER_SECTIONS:
            notes.append(f"skipped adapter section {section!r}")
            continue
        driver = LEGACY_DRIVERS.get(section)
        if driver is None:
            notes.append(f"skipped unknown section {section!r}")
            continue
        for entry in entries or []:
            title = _entry_name(section, entry)
            connection = legacy_connection(entry, driver)
            if driver == "scontel.sis_block":
                key = connection.link_key
                instrument_id = sis_blocks.get(key)
                if instrument_id is None:
                    instrument_id = next_id("sis_block", instruments)
                    sis_blocks[key] = instrument_id
                    instruments[instrument_id] = InstrumentConfig(
                        driver=driver,
                        connection=connection,
                        title=f"Scontel SIS block {len(sis_blocks)}",
                    )
                else:
                    notes.append(f"{title!r} merged into {instrument_id}")
                # One legacy SIS config = a bias and a coil device on the block
                sis_count += 1
                devices = instruments[instrument_id].devices
                devices[f"sis_bias_{sis_count}"] = DeviceConfig(
                    kind="sis_bias",
                    channel=entry.get("bias_dev", "DEV4"),
                    title=title,
                    settings={
                        "offset_voltage": _offset(entry.get("offset_voltage")),
                        "offset_current": _offset(entry.get("offset_current")),
                    },
                    metadata=(
                        {"calibration_coefficients": entry["calibration_coefficients"]}
                        if entry.get("calibration_coefficients")
                        else {}
                    ),
                )
                devices[f"sis_coil_{sis_count}"] = DeviceConfig(
                    kind="sis_coil",
                    channel=entry.get("ctrl_dev", "DEV3"),
                    title=f"{title} coil",
                )
                continue
            instrument_id = next_id(instrument_type(driver), instruments)
            instruments[instrument_id] = InstrumentConfig(
                driver=driver, connection=connection, title=title
            )

    if include_state_defaults:
        for instrument_id, spec in _state_defaults().items():
            if instrument_id not in instruments:
                instruments[instrument_id] = spec
                notes.append(f"added {instrument_id} from legacy state defaults")

    config = StationConfig(
        name=name,
        instruments=dict(instruments),
        description="Imported from the legacy settings.ini",
    ).validate()
    return config, notes


def read_legacy_settings(path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Read [Configs] of a legacy settings.ini (QVariant encoded, needs PySide6)."""
    try:
        from PySide6.QtCore import QSettings
    except ImportError as e:
        raise StationError("Reading legacy settings.ini needs PySide6") from e
    settings = QSettings(str(path), QSettings.IniFormat)
    settings.beginGroup("Configs")
    configs: Dict[str, List[Dict[str, Any]]] = {}
    for key in settings.childKeys():
        value = settings.value(key)
        if isinstance(value, dict):
            value = [value]
        configs[key] = [dict(entry) for entry in (value or [])]
    settings.endGroup()
    return configs


def import_legacy_settings(
    path: str, *, name: Optional[str] = None, include_state_defaults: bool = True
) -> Tuple[StationConfig, List[str]]:
    return station_from_legacy(
        read_legacy_settings(path),
        name=name or "legacy",
        include_state_defaults=include_state_defaults,
    )
