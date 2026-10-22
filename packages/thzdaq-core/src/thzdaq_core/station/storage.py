"""Station profiles as plain dicts and YAML files (version 2; version 1 is migrated)."""

import logging
import re
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml
from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.transport.base import ConnectionSpec

from thzdaq_core.errors import StationError
from thzdaq_core.station.config import DeviceConfig, InstrumentConfig, StationConfig
from thzdaq_core.station.kinds import DROPPED_KINDS

FORMAT_VERSION = 2
logger = logging.getLogger(__name__)
PathLike = Union[str, Path]


class ProfileLoader(yaml.SafeLoader):
    """SafeLoader that reads 1e9 / 2.5e-3 as numbers, like YAML 1.2 and JSON.

    YAML 1.1 (PyYAML) needs a dot and a signed exponent, so "500.0e9" or "5e9"
    would silently become strings in a bench profile.
    """


ProfileLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"""^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+]?[0-9]+)?
        |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
        |\.[0-9_]+(?:[eE][-+]?[0-9]+)?
        |[-+]?\.(?:inf|Inf|INF)
        |\.(?:nan|NaN|NAN))$""",
        re.X,
    ),
    list("-+0123456789."),
)


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
        }
    )


def _known_keys(section: str, data: Dict[str, Any], allowed: List[str]):
    if not isinstance(data, dict):
        raise StationError(f"{section}: expected a mapping")
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
    _known_keys("station", data, ["version", "name", "description", "instruments"])
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


def load_station(path: PathLike) -> StationConfig:
    try:
        data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=ProfileLoader)
    except OSError as e:
        raise StationError(f"Can't read station profile {path}: {e}") from e
    except yaml.YAMLError as e:
        raise StationError(f"{path}: invalid YAML: {e}") from e
    return station_from_dict(data)


def dump_station(config: StationConfig) -> str:
    return yaml.safe_dump(
        station_to_dict(config.validate()), sort_keys=False, allow_unicode=True
    )


def save_station(config: StationConfig, path: PathLike) -> None:
    Path(path).write_text(dump_station(config), encoding="utf-8")
