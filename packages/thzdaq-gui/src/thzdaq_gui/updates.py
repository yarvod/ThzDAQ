"""Updates from GitHub releases: find a newer build, download it, hand over to the updater.

Releases are tagged vX.Y.Z (vX.Y.Z-rc.N for pre-releases) and carry one asset
per platform, ThzDAQ_Windows_x64_<tag>.zip, with the ThzDAQ folder inside.
"""

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import requests

from thzdaq_gui.version import REPO_SLUG, __version__

API = "https://api.github.com"
APP_NAME = "ThzDAQ"
UPDATER = "updater.exe"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-?([a-z]+)\.?(\d+))?$", re.IGNORECASE)


class UpdateError(RuntimeError):
    pass


def parse_version(tag: str) -> Tuple[int, int, int, int, str, int]:
    """Sortable key: a pre-release (rc, beta) sorts before its release."""
    match = _VERSION.match(tag.strip())
    if match is None:
        raise ValueError(f"not a version tag: {tag!r}")
    major, minor, patch, label, number = match.groups()
    final = 1 if label is None else 0
    return int(major), int(minor), int(patch), final, (label or "").lower(), int(number or 0)


def is_newer(tag: str, current: str = __version__) -> bool:
    try:
        return parse_version(tag) > parse_version(current)
    except ValueError:
        return False


def platform_asset_suffix() -> Optional[str]:
    """Asset name part for this machine; builds exist for Windows x64 only."""
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in ("amd64", "x86_64", "x64"):
        return "Windows_x64"
    return None


def asset_name(tag: str, suffix: str = "Windows_x64") -> str:
    return f"{APP_NAME}_{suffix}_{tag}.zip"


@dataclass(frozen=True)
class Release:
    tag: str
    published_at: str
    notes: str
    prerelease: bool
    page_url: str
    download_url: Optional[str] = None
    size: int = 0

    @property
    def date(self) -> str:
        return self.published_at[:10]


def release_from_json(data: dict, suffix: Optional[str]) -> Release:
    tag = data.get("tag_name") or ""
    download_url, size = None, 0
    if suffix is not None:
        for asset in data.get("assets") or []:
            if asset.get("name") == asset_name(tag, suffix):
                download_url = asset.get("browser_download_url")
                size = int(asset.get("size") or 0)
    return Release(
        tag=tag,
        published_at=data.get("published_at") or "",
        notes=data.get("body") or "",
        prerelease=bool(data.get("prerelease")),
        page_url=data.get("html_url") or "",
        download_url=download_url,
        size=size,
    )


def fetch_releases(
    repo: str = REPO_SLUG, limit: int = 20, timeout: float = 10.0
) -> List[Release]:
    """Published version releases, newest first."""
    url = f"{API}/repos/{repo}/releases?per_page={limit}"
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise UpdateError(f"GitHub is not reachable: {e}") from e
    if response.status_code != 200:
        raise UpdateError(f"GitHub answered {response.status_code}: {response.text[:300]}")
    suffix = platform_asset_suffix()
    releases = []
    for data in response.json():
        if data.get("draft"):
            continue
        release = release_from_json(data, suffix)
        try:
            parse_version(release.tag)
        except ValueError:
            continue
        releases.append(release)
    releases.sort(key=lambda r: parse_version(r.tag), reverse=True)
    return releases


def latest_update(
    releases: List[Release], current: str = __version__, prereleases: bool = False
) -> Optional[Release]:
    for release in releases:
        if release.prerelease and not prereleases:
            continue
        if release.download_url and is_newer(release.tag, current):
            return release
    return None


Progress = Callable[[int, int], None]


def download(
    release: Release,
    folder: Path,
    progress: Optional[Progress] = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Optional[Path]:
    """Download and unpack the release; returns the new application folder."""
    if not release.download_url:
        raise UpdateError(f"{release.tag} has no build for this platform")
    archive = folder / asset_name(release.tag)
    try:
        with requests.get(release.download_url, stream=True, timeout=30) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or release.size or 0)
            done = 0
            with open(archive, "wb") as f:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if cancelled():
                        return None
                    f.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
    except requests.RequestException as e:
        raise UpdateError(f"Download failed: {e}") from e
    root = unpack(archive, folder / "unpacked")
    archive.unlink()
    return root


def unpack(archive: Path, target: Path) -> Path:
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
    except zipfile.BadZipFile as e:
        raise UpdateError(f"Broken archive {archive.name}: {e}") from e
    items = list(target.iterdir())
    root = items[0] if len(items) == 1 and items[0].is_dir() else target
    if not (root / f"{APP_NAME}.exe").exists():
        raise UpdateError(f"{archive.name} has no {APP_NAME}.exe")
    return root


def install_dir() -> Optional[Path]:
    """Folder of the running build; None when running from sources."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def can_self_update() -> bool:
    folder = install_dir()
    return (
        folder is not None
        and platform_asset_suffix() is not None
        and (folder / UPDATER).exists()
    )


def launch_updater(source: Path, target: Optional[Path] = None) -> None:
    """Start the updater from a temporary copy; the caller quits right after.

    The copy lets the updater replace its own file in the install folder.
    """
    target = target or install_dir()
    if target is None:
        raise UpdateError("Running from sources: update with git instead")
    updater = Path(source) / UPDATER
    if not updater.exists():
        updater = target / UPDATER
    if not updater.exists():
        raise UpdateError(f"{UPDATER} is missing in {target}")
    runner = Path(tempfile.mkdtemp(prefix="thzdaq_updater_")) / UPDATER
    shutil.copy2(updater, runner)
    command = [
        str(runner),
        "--pid", str(os.getpid()),
        "--source", str(source),
        "--target", str(target),
        "--exe", str(Path(sys.executable) if install_dir() == target else target / f"{APP_NAME}.exe"),
    ]  # fmt: skip
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(command, creationflags=flags, close_fds=True)
