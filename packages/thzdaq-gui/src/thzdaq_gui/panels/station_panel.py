from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.station.cli import capability_names


class StationPanel(QWidget):
    """Load a bench profile, see instruments and roles, check them on hardware."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)

        buttons = QHBoxLayout()
        self.btnOpen = QPushButton("Open profile…")
        self.btnOpen.clicked.connect(self.open_profile)
        self.btnEdit = QPushButton("Edit…")
        self.btnEdit.clicked.connect(self.edit_profile)
        self.btnReload = QPushButton("Reload")
        self.btnReload.clicked.connect(
            lambda: self.session.reload(self.simulate.isChecked())
        )
        self.simulate = QCheckBox("Simulate")
        self.simulate.toggled.connect(self.toggle_simulate)
        buttons.addWidget(self.btnOpen)
        buttons.addWidget(self.btnEdit)
        buttons.addWidget(self.btnReload)
        buttons.addWidget(self.simulate)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.title = QLabel("No station")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Details", "Status"])
        self.tree.setColumnWidth(0, 160)
        self.tree.setColumnWidth(1, 220)
        layout.addWidget(self.tree)

        self.btnCheck = QPushButton("Check roles")
        self.btnCheck.clicked.connect(self.check_roles)
        layout.addWidget(self.btnCheck)

        self.role_items = {}
        session.station_changed.connect(self.show_station)
        session.runner.running_changed.connect(
            lambda running: self.btnCheck.setEnabled(not running)
        )
        self.show_station(session.station)

    def open_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open station profile", "stations", "Station profiles (*.yaml *.yml)"
        )
        if path:
            self.session.load_station(path, self.simulate.isChecked())

    def edit_profile(self) -> None:
        from thzdaq_gui.profile_editor import ProfileEditor

        station = self.session.station
        if station is None:
            return
        editor = ProfileEditor(station.config, str(self.session.path), self)
        if editor.exec() and editor.saved_config is not None:
            self.session.load_station(editor.path, self.simulate.isChecked())

    def toggle_simulate(self, value: bool) -> None:
        if self.session.station is not None and self.session.simulate != value:
            self.session.reload(value)

    def show_station(self, station) -> None:
        self.tree.clear()
        self.role_items.clear()
        has_station = station is not None
        self.btnReload.setEnabled(has_station)
        self.btnEdit.setEnabled(has_station)
        self.btnCheck.setEnabled(has_station)
        if not has_station:
            self.title.setText("No station: open a profile from stations/")
            return
        self.simulate.blockSignals(True)
        self.simulate.setChecked(self.session.simulate)
        self.simulate.blockSignals(False)
        mode = " — SIMULATION" if self.session.simulate else ""
        self.title.setText(f"<b>{station.name}</b>{mode}<br>{self.session.path}")

        config = station.config
        instruments = QTreeWidgetItem(self.tree, ["Instruments"])
        for instrument_id, spec in config.instruments.items():
            where = spec.connection.link_key if spec.connection else "-"
            QTreeWidgetItem(instruments, [instrument_id, f"{spec.driver} {where}", ""])
        roles = QTreeWidgetItem(self.tree, ["Roles"])
        for role, spec in config.roles.items():
            part = spec.instrument
            if spec.channel is not None:
                part += f".{spec.accessor}({spec.channel!r})"
            if spec.adapter:
                part += f" → {spec.adapter}"
            item = QTreeWidgetItem(roles, [role, part, ""])
            self.role_items[role] = item
        self.tree.expandAll()

    def check_roles(self) -> None:
        station = self.session.station
        if station is None:
            return
        for role, item in self.role_items.items():
            item.setText(2, "…")

            def job(role=role):
                return capability_names(station.role(role))

            def done(caps, item=item):
                item.setText(2, ", ".join(caps) or "ok")
                item.setForeground(2, QColor("darkgreen"))

            def failed(error, item=item):
                item.setText(2, f"{error}")
                item.setForeground(2, QColor("red"))

            self.session.worker.submit(job, done, failed)
