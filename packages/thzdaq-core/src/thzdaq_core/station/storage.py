"""Station profiles as plain dicts and YAML files."""

import re
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml
from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.transport.base import ConnectionSpec

from thzdaq_core.errors import StationError
from thzdaq_core.station.config import InstrumentConfig, RoleConfig, StationConfig

FORMAT_VERSION = 1
PathLike = Union[str, Path]


class _Loader(yaml.SafeLoader):
    """SafeLoader that reads 1e9 / 2.5e-3 as numbers, like YAML 1.2 and JSON.

    YAML 1.1 (PyYAML) needs a dot and a signed exponent, so "500.0e9" or "5e9"
    would silently become strings in a bench profile.
    """


_Loader.add_implicit_resolver(
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


def station_to_dict(config: StationConfig) -> Dict[str, Any]:
    instruments = {}
    for instrument_id, spec in config.instruments.items():
        item = {
            "driver": spec.driver,
            "connection": connection_to_dict(spec.connection)
            if spec.connection
            else None,
            "options": spec.options,
            "simulate": spec.simulate,
            "sim_options": spec.sim_options,
            "title": spec.title,
            "metadata": spec.metadata,
        }
        instruments[instrument_id] = _drop_empty(item)
    roles = {}
    for role, spec in config.roles.items():
        item = {
            "instrument": spec.instrument,
            "channel": spec.channel,
            "accessor": spec.accessor if spec.accessor != "channel" else None,
            "adapter": spec.adapter,
            "options": spec.options,
            "attributes": spec.attributes,
            "description": spec.description,
            "metadata": spec.metadata,
        }
        roles[role] = _drop_empty(item)
    return _drop_empty(
        {
            "version": FORMAT_VERSION,
            "name": config.name,
            "description": config.description,
            "instruments": instruments,
            "roles": roles,
        }
    )


def _known_keys(section: str, data: Dict[str, Any], allowed: List[str]):
    unknown = set(data) - set(allowed)
    if unknown:
        raise StationError(f"{section}: unknown keys {sorted(unknown)}")


def station_from_dict(data: Dict[str, Any]) -> StationConfig:
    if not isinstance(data, dict):
        raise StationError("Station profile must be a mapping")
    version = data.get("version", FORMAT_VERSION)
    if version != FORMAT_VERSION:
        raise StationError(f"Unsupported station profile version {version}")
    _known_keys(
        "station", data, ["version", "name", "description", "instruments", "roles"]
    )
    instruments = {}
    for instrument_id, item in (data.get("instruments") or {}).items():
        _known_keys(
            f"instrument {instrument_id}",
            item,
            [
                "driver",
                "connection",
                "options",
                "simulate",
                "sim_options",
                "title",
                "metadata",
            ],
        )
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
        )
    roles = {}
    for role, item in (data.get("roles") or {}).items():
        _known_keys(
            f"role {role}",
            item,
            [
                "instrument",
                "channel",
                "accessor",
                "adapter",
                "options",
                "attributes",
                "description",
                "metadata",
            ],
        )
        if "instrument" not in item:
            raise StationError(f"role {role}: instrument is required")
        roles[role] = RoleConfig(
            instrument=item["instrument"],
            channel=item.get("channel"),
            accessor=item.get("accessor", "channel"),
            adapter=item.get("adapter"),
            options=dict(item.get("options") or {}),
            attributes=dict(item.get("attributes") or {}),
            description=item.get("description", ""),
            metadata=dict(item.get("metadata") or {}),
        )
    return StationConfig(
        name=data.get("name", "station"),
        instruments=instruments,
        roles=roles,
        description=data.get("description", ""),
    ).validate()


def load_station(path: PathLike) -> StationConfig:
    try:
        data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_Loader)
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
