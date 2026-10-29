"""Station profiles in YAML files: the profile format (domain/station/profile.py)
read from and written to disk."""

import re
from pathlib import Path
from typing import Union

import yaml

from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.station.config import StationConfig
from thzdaq_core.domain.station.profile import station_from_dict, station_to_dict

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
