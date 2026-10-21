import subprocess
import sys
import zipfile

import pytest
from thzdaq_gui import updater, updates
from thzdaq_gui.updates import Release, UpdateError


def release_json(tag, prerelease=False, draft=False, assets=None):
    return {
        "tag_name": tag,
        "published_at": "2026-10-22T10:00:00Z",
        "body": f"notes {tag}",
        "prerelease": prerelease,
        "draft": draft,
        "html_url": f"https://github.com/yarvod/ThzDAQ/releases/tag/{tag}",
        "assets": (
            assets
            if assets is not None
            else [
                {"name": f"ThzDAQ_Windows_x64_{tag}.zip", "size": 10,
                 "browser_download_url": f"https://example.org/{tag}.zip"},
                {"name": f"ThzDAQ_macOS_arm64_{tag}.zip", "size": 10,
                 "browser_download_url": "https://example.org/mac.zip"},
            ]
        ),
    }  # fmt: skip


class FakeResponse:
    def __init__(self, payload=None, chunks=(), status_code=200):
        self.payload = payload
        self.chunks = chunks
        self.status_code = status_code
        self.headers = {"content-length": str(sum(len(c) for c in chunks))}
        self.text = ""

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        return iter(self.chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_build(folder, files):
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return folder


def tree(folder):
    return {
        str(p.relative_to(folder)).replace("\\", "/"): p.read_text()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


class TestVersions:
    def test_order(self):
        order = ["v0.2.0", "v0.3.0-rc.1", "v0.3.0-rc.2", "v0.3.0", "0.3.1", "v1.0.0"]
        keys = [updates.parse_version(tag) for tag in order]
        assert keys == sorted(keys)

    def test_is_newer(self):
        assert updates.is_newer("v0.3.0", "0.2.0")
        assert not updates.is_newer("v0.3.0-rc.1", "0.3.0")
        assert not updates.is_newer("nightly", "0.2.0")
        with pytest.raises(ValueError):
            updates.parse_version("new103b1")


class TestReleases:
    def test_fetch_filters_and_sorts(self, monkeypatch):
        payload = [
            release_json("v0.2.0"),
            release_json("v0.4.0", draft=True),
            release_json("nightly"),
            release_json("v0.3.0-rc.1", prerelease=True),
            release_json("v0.3.0", assets=[]),
        ]
        monkeypatch.setattr(updates, "platform_asset_suffix", lambda: "Windows_x64")
        monkeypatch.setattr(
            updates.requests, "get", lambda *a, **k: FakeResponse(payload)
        )
        releases = updates.fetch_releases()
        assert [r.tag for r in releases] == ["v0.3.0", "v0.3.0-rc.1", "v0.2.0"]
        assert releases[0].download_url is None
        assert releases[1].download_url == "https://example.org/v0.3.0-rc.1.zip"
        assert releases[2].date == "2026-10-22"
        assert updates.latest_update(releases, "0.1.0").tag == "v0.2.0"
        assert updates.latest_update(releases, "0.1.0", prereleases=True).tag == (
            "v0.3.0-rc.1"
        )
        assert updates.latest_update(releases, "0.3.0", prereleases=True) is None

    def test_other_platforms_get_no_download(self):
        release = updates.release_from_json(release_json("v0.3.0"), None)
        assert release.download_url is None and release.notes == "notes v0.3.0"

    def test_github_errors(self, monkeypatch):
        monkeypatch.setattr(
            updates.requests,
            "get",
            lambda *a, **k: FakeResponse(status_code=403),
        )
        with pytest.raises(UpdateError, match="403"):
            updates.fetch_releases()


class TestDownload:
    def archive_bytes(self, tmp_path, files):
        path = tmp_path / "src.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for name, text in files.items():
                zf.writestr(name, text)
        return path.read_bytes()

    def test_download_and_unpack(self, tmp_path, monkeypatch):
        data = self.archive_bytes(
            tmp_path, {"ThzDAQ/ThzDAQ.exe": "exe", "ThzDAQ/_internal/a.pyd": "a"}
        )
        chunks = [data[:100], data[100:]]
        monkeypatch.setattr(
            updates.requests, "get", lambda *a, **k: FakeResponse(chunks=chunks)
        )
        seen = []
        release = Release("v0.3.0", "", "", False, "", "https://x/a.zip", len(data))
        work = tmp_path / "work"
        work.mkdir()
        root = updates.download(release, work, progress=lambda d, t: seen.append(d))
        assert root.name == "ThzDAQ" and (root / "_internal" / "a.pyd").exists()
        assert seen[-1] == len(data)
        assert not (work / updates.asset_name("v0.3.0")).exists()

    def test_cancel_and_bad_archives(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            updates.requests, "get", lambda *a, **k: FakeResponse(chunks=[b"x"])
        )
        release = Release("v0.3.0", "", "", False, "", "https://x/a.zip")
        assert updates.download(release, tmp_path, cancelled=lambda: True) is None
        with pytest.raises(UpdateError, match="Broken"):
            updates.download(release, tmp_path)
        (tmp_path / "plain.zip").write_bytes(
            self.archive_bytes(tmp_path, {"readme.txt": "x"})
        )
        with pytest.raises(UpdateError, match="no ThzDAQ.exe"):
            updates.unpack(tmp_path / "plain.zip", tmp_path / "out")
        with pytest.raises(UpdateError, match="no build"):
            updates.download(Release("v1.0.0", "", "", False, ""), tmp_path)

    def test_running_from_sources_cannot_self_update(self):
        assert updates.install_dir() is None and not updates.can_self_update()
        with pytest.raises(UpdateError, match="sources"):
            updates.launch_updater(updates.Path("."))


class TestUpdater:
    OLD = {
        "ThzDAQ.exe": "old exe",
        "updater.exe": "old updater",
        "_internal/old_only.pyd": "stale",
        "_internal/base.zip": "old base",
        "stations/lab.yaml": "edited on the bench",
        "data/2026-10-01/run.jsonl": "measurement",
    }
    NEW = {
        "ThzDAQ.exe": "new exe",
        "updater.exe": "new updater",
        "_internal/base.zip": "new base",
        "stations/lab.yaml": "shipped",
        "stations/2sb.example.yaml": "example",
    }

    def test_install_replaces_build_and_keeps_bench_files(self, tmp_path):
        target = make_build(tmp_path / "app", self.OLD)
        source = make_build(tmp_path / "new", self.NEW)
        updater.install(source, target)
        assert tree(target) == {
            "ThzDAQ.exe": "new exe",
            "updater.exe": "new updater",
            "_internal/base.zip": "new base",
            "stations/lab.yaml": "edited on the bench",
            "stations/2sb.example.yaml": "example",
            "data/2026-10-01/run.jsonl": "measurement",
        }
        assert not (target / updater.BACKUP).exists()

    def test_failed_install_restores_the_old_build(self, tmp_path, monkeypatch):
        target = make_build(tmp_path / "app", self.OLD)
        source = make_build(tmp_path / "new", self.NEW)
        real_copy = updater.copy

        def broken(src, dst):
            if src.name == "_internal":
                raise OSError("disk full")
            real_copy(src, dst)

        monkeypatch.setattr(updater, "copy", broken)
        with pytest.raises(OSError, match="disk full"):
            updater.install(source, target)
        assert tree(target) == self.OLD
        assert not (target / updater.BACKUP).exists()

    def test_main_waits_installs_and_starts(self, tmp_path, monkeypatch):
        target = make_build(tmp_path / "app", self.OLD)
        source = make_build(tmp_path / "new", self.NEW)
        finished = subprocess.Popen([sys.executable, "-c", "pass"])
        finished.wait()
        started = []
        monkeypatch.setattr(
            updater.subprocess, "Popen", lambda cmd, **k: started.append(cmd)
        )
        code = updater.main(
            ["--pid", str(finished.pid), "--source", str(source),
             "--target", str(target), "--exe", str(target / "ThzDAQ.exe")]
        )  # fmt: skip
        assert code == 0 and started == [[str(target / "ThzDAQ.exe")]]
        assert (target / "ThzDAQ.exe").read_text() == "new exe"
        assert not source.exists() and (target / updater.LOG).exists()

    def test_updater_needs_only_the_standard_library(self):
        code = (
            "import sys; import thzdaq_gui.updater;"
            "print(sorted(m for m in sys.modules if m.split('.')[0] in "
            "('PySide6', 'requests', 'numpy', 'thzdaq_core', 'thzdaq_instruments')))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout
        assert out.strip() == "[]"


class TestDialog:
    def test_lists_releases(self, app, monkeypatch):
        from thzdaq_gui.update_dialog import UpdateDialog

        monkeypatch.setattr(updates, "platform_asset_suffix", lambda: "Windows_x64")
        releases = [
            updates.release_from_json(release_json("v9.0.0-rc.1", True), "Windows_x64"),
            updates.release_from_json(release_json("v9.0.0"), "Windows_x64"),
            updates.release_from_json(release_json("v0.1.0", assets=[]), "Windows_x64"),
        ]
        dialog = UpdateDialog(quit_app=lambda: None)
        dialog.set_releases(releases)
        assert "v9.0.0" in dialog.status.text()
        assert dialog.list.count() == 2
        assert "no build" in dialog.list.item(1).text()
        assert "notes v9.0.0" in dialog.notes.toPlainText()
        assert not dialog.btnInstall.isEnabled()  # running from sources
        dialog.prereleases.setChecked(True)
        assert dialog.list.count() == 3

    def test_background_job(self, app, wait):
        from thzdaq_gui.update_dialog import Background

        results, errors = [], []
        ok = Background(lambda task: 42)
        ok.done.connect(results.append)
        ok.start()
        bad = Background(lambda task: 1 / 0)
        bad.failed.connect(errors.append)
        bad.start()
        wait(lambda: results and errors)
        assert results == [42] and "division" in errors[0]

    def test_help_menu(self, app, session, monkeypatch, wait):
        from thzdaq_gui.main_window import MainWindow

        monkeypatch.setattr(updates, "fetch_releases", lambda: [])
        window = MainWindow(session, restore_layout=False)
        titles = [a.text() for a in window.menuBar().actions()]
        assert "&Help" in titles and window.windowTitle().startswith("ThzDAQ ")
        window.show_updates()
        assert window.updateDialog.isVisible()
        wait(lambda: "latest version" in window.updateDialog.status.text())
        window.updateDialog.close()
