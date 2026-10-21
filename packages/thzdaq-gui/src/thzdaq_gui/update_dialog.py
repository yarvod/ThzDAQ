"""Help → Check for updates: list GitHub releases, download one and restart into it."""

import logging
import tempfile
import threading
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from thzdaq_gui import updates
from thzdaq_gui.version import REPO_SLUG, __version__

logger = logging.getLogger(__name__)
RELEASES_PAGE = f"https://github.com/{REPO_SLUG}/releases"


class Background(QObject):
    """Runs one job in a daemon thread: a slow network never blocks quitting."""

    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, job: Callable[["Background"], object], parent=None):
        super().__init__(parent)
        self.job = job
        self.cancelled = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="Updates", daemon=True).start()

    def _run(self) -> None:
        try:
            result = self.job(self)
        except Exception as e:
            logger.warning("Update job failed: %s", e)
            self._emit(self.failed, str(e))
            return
        if not self.cancelled.is_set():
            self._emit(self.done, result)

    @staticmethod
    def _emit(signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:  # receiver already deleted: the window has closed
            pass


def fetch_job(task: Background) -> List[updates.Release]:
    return updates.fetch_releases()


def download_job(release: updates.Release) -> Callable[[Background], object]:
    def job(task: Background) -> Optional[str]:
        folder = Path(tempfile.mkdtemp(prefix="thzdaq_update_"))
        root = updates.download(
            release,
            folder,
            progress=lambda done, total: task._emit(task.progress, done, total),
            cancelled=task.cancelled.is_set,
        )
        return str(root) if root is not None else None

    return job


class UpdateDialog(QDialog):
    """quit_app closes the main window once the updater has started."""

    def __init__(self, quit_app: Callable[[], None], busy=lambda: False, parent=None):
        super().__init__(parent)
        self.quit_app = quit_app
        self.busy = busy
        self.releases: List[updates.Release] = []
        self.downloader: Optional[Background] = None
        self.setWindowTitle("ThzDAQ updates")
        self.resize(620, 480)

        layout = QVBoxLayout(self)
        self.status = QLabel(f"Installed version: <b>{__version__}</b>. Checking…")
        layout.addWidget(self.status)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.show_notes)
        layout.addWidget(self.list, 2)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        layout.addWidget(self.notes, 1)
        self.prereleases = QCheckBox("Show pre-releases")
        self.prereleases.toggled.connect(self.populate)
        layout.addWidget(self.prereleases)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.btnInstall = QPushButton("Install")
        self.btnInstall.clicked.connect(self.install)
        self.btnPage = QPushButton("Open page")
        self.btnPage.clicked.connect(self.open_page)
        buttons.addButton(self.btnInstall, QDialogButtonBox.ActionRole)
        buttons.addButton(self.btnPage, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.btnInstall.setEnabled(False)

        self.fetcher = Background(fetch_job, self)
        self.fetcher.done.connect(self.set_releases)
        self.fetcher.failed.connect(
            lambda message: self.status.setText(f"Release check failed: {message}")
        )

    def check(self) -> None:
        self.fetcher.start()

    def set_releases(self, releases: List[updates.Release]) -> None:
        self.releases = releases
        newest = updates.latest_update(releases)
        if newest is not None:
            text = f"Version <b>{newest.tag}</b> is available."
        else:
            text = "This is the latest version."
        if not updates.can_self_update():
            text += " Automatic install works in the Windows build only."
        self.status.setText(f"Installed version: <b>{__version__}</b>. {text}")
        self.populate()

    def populate(self) -> None:
        self.list.clear()
        current = None
        for release in self.releases:
            if release.prerelease and not self.prereleases.isChecked():
                continue
            text = f"{release.tag}   {release.date}"
            if release.prerelease:
                text += "   pre-release"
            if updates.parse_version(release.tag) == updates.parse_version(__version__):
                text += "   installed"
            elif release.download_url is None:
                text += "   no build for this platform"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, release)
            self.list.addItem(item)
            if current is None:
                current = item
        if current is not None:
            self.list.setCurrentItem(current)

    def selected(self) -> Optional[updates.Release]:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def show_notes(self, *_) -> None:
        release = self.selected()
        self.notes.setMarkdown(release.notes if release else "")
        self.btnInstall.setEnabled(
            release is not None
            and release.download_url is not None
            and updates.can_self_update()
        )

    def open_page(self) -> None:
        release = self.selected()
        url = release.page_url if release and release.page_url else RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(url))

    def install(self) -> None:
        release = self.selected()
        if release is None or release.download_url is None:
            return
        if self.busy():
            QMessageBox.warning(
                self, "Update", "Stop the running measurement before updating."
            )
            return
        answer = QMessageBox.question(
            self,
            "Update",
            f"Install ThzDAQ {release.tag}? The application restarts; "
            "bench profiles in stations/ are kept.",
        )
        if answer != QMessageBox.Yes:
            return
        progress = QProgressDialog(f"Downloading {release.tag}…", "Cancel", 0, 0, self)
        progress.setWindowTitle("Update")
        progress.setMinimumDuration(0)
        self.downloader = Background(download_job(release), self)

        def on_progress(done: int, total: int) -> None:
            if total:
                progress.setMaximum(total // 1024)
                progress.setValue(done // 1024)

        def on_failed(message: str) -> None:
            progress.close()
            QMessageBox.critical(self, "Update", message)

        def on_done(source: Optional[str]) -> None:
            progress.close()
            if source is None:
                return
            try:
                updates.launch_updater(Path(source))
            except Exception as e:
                QMessageBox.critical(self, "Update", str(e))
                return
            self.accept()
            self.quit_app()

        self.downloader.progress.connect(on_progress)
        self.downloader.failed.connect(on_failed)
        self.downloader.done.connect(on_done)
        progress.canceled.connect(self.downloader.cancelled.set)
        self.downloader.start()
