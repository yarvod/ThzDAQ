"""Station profiles in YAML files: the profile format (domain/station/profile.py)
read from and written to disk. A profile written over keeps its earlier
versions in .history/ next to it (stations/.history/lab.20261110-142501-123456.yaml)."""

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Union

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


HISTORY = ".history"  # the folder next to a profile with its earlier versions
KEPT = 50  # versions of one profile kept there
STAMP = "%Y%m%d-%H%M%S-%f"


def versions(path: PathLike) -> List[Path]:
    """The earlier versions of a profile, oldest first."""
    path = Path(path)
    name = re.compile(
        re.escape(path.stem) + r"\.\d{8}-\d{6}-\d{6}" + re.escape(path.suffix)
    )
    folder = path.parent / HISTORY
    if not folder.is_dir():
        return []
    return sorted(item for item in folder.iterdir() if name.fullmatch(item.name))


def keep_version(path: Path) -> None:
    """The profile as it is now into .history/; the oldest beyond KEPT go."""
    folder = path.parent / HISTORY
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime(STAMP)
    shutil.copy2(path, folder / f"{path.stem}.{stamp}{path.suffix}")
    for old in versions(path)[:-KEPT]:
        old.unlink()


class YamlProfiles:
    """Station profiles as YAML files (application.ports.ProfileRepository)."""

    def load(self, path: PathLike) -> StationConfig:
        return load_station(path)

    def save(self, config: StationConfig, path: PathLike) -> None:
        """Written over, the file it was is kept in .history/ (unless the
        profile is the same)."""
        path = Path(path)
        text = dump_station(config)
        if path.exists():
            if path.read_text(encoding="utf-8") == text:
                return
            keep_version(path)
        path.write_text(text, encoding="utf-8")

    def text(self, config: StationConfig) -> str:
        return dump_station(config)
