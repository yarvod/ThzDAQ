"""Earlier versions of a file kept in .history/ next to it, each under its
name with a stamp (stations/.history/lab.20261110-142501-123456.yaml): a
profile written over, a script of the library deleted."""

import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Union

PathLike = Union[str, Path]

HISTORY = ".history"  # the folder next to a file with its earlier versions
KEPT = 50  # versions of one file kept there
STAMP = "%Y%m%d-%H%M%S-%f"


def versions(path: PathLike) -> List[Path]:
    """The earlier versions of a file, oldest first."""
    path = Path(path)
    name = re.compile(
        re.escape(path.stem) + r"\.\d{8}-\d{6}-\d{6}" + re.escape(path.suffix)
    )
    folder = path.parent / HISTORY
    if not folder.is_dir():
        return []
    return sorted(item for item in folder.iterdir() if name.fullmatch(item.name))


def keep_version(path: Path) -> Path:
    """The file as it is now into .history/, where it is kept; the oldest
    beyond KEPT go."""
    folder = path.parent / HISTORY
    folder.mkdir(exist_ok=True)
    earlier = versions(path)
    stamp = datetime.now()
    if earlier:
        latest = (
            earlier[-1].name.removeprefix(f"{path.stem}.").removesuffix(path.suffix)
        )
        # The timestamp is a version id: clocks can repeat or move backwards.
        stamp = max(stamp, datetime.strptime(latest, STAMP) + timedelta(microseconds=1))
    saved = folder / f"{path.stem}.{stamp.strftime(STAMP)}{path.suffix}"
    with path.open("rb") as source, saved.open("xb") as target:
        shutil.copyfileobj(source, target)
    shutil.copystat(path, saved)
    for old in (earlier + [saved])[:-KEPT]:
        old.unlink()
    return saved
