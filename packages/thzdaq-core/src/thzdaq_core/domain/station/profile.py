"""The station profile format: plain dicts (version 2; version 1 is migrated).

Files are read and written by the adapter (adapters/yaml_profiles.py).
"""

import logging
from dataclasses import fields
from typing import Any, Dict, List

from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.transport.base import ConnectionSpec

from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.station.config import (
    DeviceConfig,
    InstrumentConfig,
    StationConfig,
)
from thzdaq_core.domain.station.kinds import DROPPED_KINDS
from thzdaq_core.domain.station.safety import Safety, SafetyLimit

FORMAT_VERSION = 2
logger = logging.getLogger(__name__)


def connection_to_dict(spec: ConnectionSpec) -> Dict[str, Any]:
    """Only the fields that differ from defaults, so files stay short."""
    data = {"kind": spec.kind}
    for item in fields(ConnectionSpec):
        if item.name == "kind":
            continue
        value = getattr(spec, item.name)
        if value != item.default:
            data[item.name] = value
    return data


def connection_from_dict(data: Dict[str, Any]) -> ConnectionSpec:
    known = {item.name for item in fields(ConnectionSpec)}
    unknown = set(data) - known
    if unknown:
        raise StationError(f"Unknown connection fields: {sorted(unknown)}")
    try:
        return ConnectionSpec(**data)
    except (ConfigurationError, TypeError) as e:
        raise StationError(f"Invalid connection {data}: {e}") from e


def _is_empty(value: Any) -> bool:
    # Identity checks: a channel key 0 must survive, 0 == False in Python
    return (
        value is None
        or value is False
        or (isinstance(value, (str, dict)) and not value)
    )


def _drop_empty(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in data.items() if not _is_empty(v)}


def device_to_dict(spec: DeviceConfig) -> Dict[str, Any]:
    return _drop_empty(
        {
            "kind": spec.kind,
            "channel": spec.channel,
            "title": spec.title,
            "settings": spec.settings,
            "metadata": spec.metadata,
        }
    )


# Keys of a limit in the profile and the fields they fill
LIMIT_FIELDS = {
    "min": "minimum",
    "max": "maximum",
    "warn_min": "warn_minimum",
    "warn_max": "warn_maximum",
    "step": "step",
    "rate": "rate",
}
SAFETY_KEYS = ["limits", "safe_state", "hardware_protection"]


def safety_to_dict(safety: Safety) -> Dict[str, Any]:
    limits = {
        ref: {
            key: {
                name: getattr(limit, field)
                for name, field in LIMIT_FIELDS.items()
                if getattr(limit, field) is not None
            }
            for key, limit in by_key.items()
        }
        for ref, by_key in safety.limits.items()
    }
    return _drop_empty(
        {
            "limits": limits,
            "safe_state": {ref: dict(v) for ref, v in safety.safe_state.items()},
            "hardware_protection": safety.hardware_protection,
        }
    )


def _limit_from_dict(where: str, item: Any) -> SafetyLimit:
    _known_keys(where, item, list(LIMIT_FIELDS))
    values = {}
    for name, value in item.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StationError(f"{where}: {name} must be a number, got {value!r}")
        values[LIMIT_FIELDS[name]] = float(value)
    return SafetyLimit(**values)


def safety_from_dict(data: Any) -> Safety:
    _known_keys("safety", data, SAFETY_KEYS)
    # An empty key in YAML is None: the section is empty
    sections = {key: data.get(key) for key in ("limits", "safe_state")}
    sections = {key: {} if value is None else value for key, value in sections.items()}
    for key, section in sections.items():
        _mapping(f"safety {key}", section)
    limits = {}
    for ref, by_key in sections["limits"].items():
        _mapping(f"safety limits of {ref}", by_key)
        limits[ref] = {
            key: _limit_from_dict(f"safety limits of {ref} {key}", item)
            for key, item in by_key.items()
        }
    safe_state = {}
    for ref, values in sections["safe_state"].items():
        _mapping(f"safe state of {ref}", values)
        safe_state[ref] = dict(values)
    return Safety(
        limits=limits,
        safe_state=safe_state,
        hardware_protection=bool(data.get("hardware_protection", False)),
    )


def station_to_dict(config: StationConfig) -> Dict[str, Any]:
    instruments = {}
    for instrument_id, spec in config.instruments.items():
        item = {
            "driver": spec.driver,
            "title": spec.title,
            "connection": connection_to_dict(spec.connection)
            if spec.connection
            else None,
            "options": spec.options,
            "simulate": spec.simulate,
            "sim_options": spec.sim_options,
            "metadata": spec.metadata,
            "settings": spec.settings,
            "devices": {
                device_id: device_to_dict(device)
                for device_id, device in spec.devices.items()
            },
        }
        instruments[instrument_id] = _drop_empty(item)
    return _drop_empty(
        {
            "version": FORMAT_VERSION,
            "name": config.name,
            "description": config.description,
            "instruments": instruments,
            "safety": safety_to_dict(config.safety),
        }
    )


def _mapping(section: str, data: Any) -> None:
    if not isinstance(data, dict):
        raise StationError(f"{section}: expected a mapping")


def _known_keys(section: str, data: Dict[str, Any], allowed: List[str]):
    _mapping(section, data)
    unknown = set(data) - set(allowed)
    if unknown:
        raise StationError(f"{section}: unknown keys {sorted(unknown)}")


INSTRUMENT_KEYS = [
    "driver", "title", "connection", "options", "simulate", "sim_options",
    "metadata", "settings", "devices",
]  # fmt: skip
DEVICE_KEYS = ["kind", "channel", "title", "settings", "metadata"]


def device_from_dict(device_id: str, item: Dict[str, Any]) -> DeviceConfig:
    _known_keys(f"device {device_id}", item, DEVICE_KEYS)
    if not item.get("kind"):
        raise StationError(f"device {device_id}: kind is required")
    return DeviceConfig(
        kind=item["kind"],
        channel=item.get("channel"),
        title=item.get("title", ""),
        settings=dict(item.get("settings") or {}),
        metadata=dict(item.get("metadata") or {}),
    )


def station_from_dict(data: Dict[str, Any]) -> StationConfig:
    if not isinstance(data, dict):
        raise StationError("Station profile must be a mapping")
    version = data.get("version", FORMAT_VERSION)
    if version == 1:
        data = migrate_v1(data)
    elif version != FORMAT_VERSION:
        raise StationError(f"Unsupported station profile version {version}")
    data = drop_old_kinds(data)
    _known_keys(
        "station", data, ["version", "name", "description", "instruments", "safety"]
    )
    instruments = {}
    for instrument_id, item in (data.get("instruments") or {}).items():
        _known_keys(f"instrument {instrument_id}", item, INSTRUMENT_KEYS)
        if "driver" not in item:
            raise StationError(f"instrument {instrument_id}: driver is required")
        connection = item.get("connection")
        instruments[instrument_id] = InstrumentConfig(
            driver=item["driver"],
            connection=connection_from_dict(connection) if connection else None,
            options=dict(item.get("options") or {}),
            simulate=bool(item.get("simulate", False)),
            sim_options=dict(item.get("sim_options") or {}),
            title=item.get("title", ""),
            metadata=dict(item.get("metadata") or {}),
            settings=dict(item.get("settings") or {}),
            devices={
                device_id: device_from_dict(device_id, device)
                for device_id, device in (item.get("devices") or {}).items()
            },
        )
    return StationConfig(
        name=data.get("name", "station"),
        instruments=instruments,
        description=data.get("description", ""),
        safety=safety_from_dict(data.get("safety") or {}),
    ).validate()


V1_ADAPTERS = {
    "scaled_frequency": "frequency_multiplier",
    "sideband_selector": "sideband_selector",
    "switch": "switch",
}


def drop_old_kinds(data: Dict[str, Any]) -> Dict[str, Any]:
    """Devices of kinds that were dropped: a measurement chooses them now.

    An LO multiplier device becomes the generator's frequency_multiplier
    setting; IF switch and switch devices go (their channel is picked in the
    measurement).
    """
    instruments = {}
    for instrument_id, item in (data.get("instruments") or {}).items():
        item = dict(item)
        devices = {}
        for device_id, device in (item.get("devices") or {}).items():
            kind = (device or {}).get("kind")
            if kind not in DROPPED_KINDS:
                devices[device_id] = device
                continue
            if kind == "frequency_multiplier":
                multiplier = (device.get("settings") or {}).get("multiplier")
                if multiplier is not None:
                    item.setdefault("settings", {})["frequency_multiplier"] = multiplier
                logger.warning(
                    f"{instrument_id}: multiplier device {device_id!r} became the "
                    f"generator setting frequency_multiplier={multiplier}"
                )
            else:
                logger.warning(
                    f"{instrument_id}: device {device_id!r} ({kind}) is no longer "
                    "a device; choose the channel in the measurement"
                )
        if "devices" in item:
            item["devices"] = devices
        instruments[instrument_id] = item
    return {**data, "instruments": instruments}


def migrate_v1(data: Dict[str, Any]) -> Dict[str, Any]:
    """Version 1 had roles next to instruments; they become devices.

    Roles that only named an instrument or a channel need no device: it is
    selected directly now.
    """
    instruments = {k: dict(v) for k, v in (data.get("instruments") or {}).items()}
    for role, item in (data.get("roles") or {}).items():
        target = instruments.get(item.get("instrument"))
        if target is None:
            raise StationError(f"role {role}: unknown instrument")
        adapter = item.get("adapter")
        if adapter in V1_ADAPTERS:
            kind, settings = V1_ADAPTERS[adapter], item.get("options") or {}
        elif item.get("accessor") == "ctrl":
            kind, settings = "sis_coil", {}
        elif str(target.get("driver", "")).endswith("sis_block"):
            kind, settings = "sis_bias", item.get("attributes") or {}
        else:
            continue
        device = {
            "kind": kind,
            "channel": item.get("channel"),
            "title": item.get("description") or role,
            "settings": dict(settings),
            "metadata": item.get("metadata") or {},
        }
        target.setdefault("devices", {})[role] = device
    return {
        "version": FORMAT_VERSION,
        "name": data.get("name", "station"),
        "description": data.get("description", ""),
        "instruments": instruments,
    }
