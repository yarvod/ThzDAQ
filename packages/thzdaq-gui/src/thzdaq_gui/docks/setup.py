"""Setup dock: the saved instruments, as in the old app, plus their devices.

Every instrument is a card: driver, connection, status and the devices it
hosts (SIS bias and coil). Add / Edit / Delete
change the station profile, which is saved at once; device docks follow.
"""

import copy
import html
import textwrap
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.errors import ProcedureError, StationError
from thzdaq_core.station.config import DeviceConfig, InstrumentConfig, StationConfig
from thzdaq_core.station.kinds import instrument_type
from thzdaq_instruments import ConfigurationError, InstrumentError, default_registry
from thzdaq_instruments.transport.base import (
    HTTP,
    KINDS,
    MODBUS_RTU,
    MODBUS_TCP,
    PROLOGIX,
    PROLOGIX_USB,
    SERIAL,
    SOCKET,
    VISA,
    ConnectionSpec,
)

from thzdaq_gui import theme
from thzdaq_gui.forms import ParameterForm
from thzdaq_gui.settings import stations_dir

# How often the Connections group shows the state of the links
REFRESH_MS = 2000

# Fields each connection kind uses, in form order
CONNECTION_FIELDS = {
    SOCKET: ("host", "port", "timeout", "read_delay"),
    PROLOGIX: ("host", "port", "gpib", "timeout", "read_delay"),
    PROLOGIX_USB: ("serial_port", "gpib", "timeout", "read_delay"),
    SERIAL: ("serial_port", "baudrate", "timeout", "read_delay"),
    VISA: ("resource", "timeout", "read_delay"),
    HTTP: ("host", "port", "timeout"),
    MODBUS_TCP: ("host", "port", "timeout"),
    MODBUS_RTU: ("serial_port", "baudrate", "timeout"),
}
KIND_TITLES = {
    SOCKET: "TCP socket",
    PROLOGIX: "Prologix GPIB-Ethernet",
    PROLOGIX_USB: "Prologix GPIB-USB",
    SERIAL: "Serial port",
    VISA: "VISA",
    HTTP: "HTTP",
    MODBUS_TCP: "Modbus TCP",
    MODBUS_RTU: "Modbus RTU",
}


def breakable_path(path) -> str:
    """A path a word-wrapped label may break after any separator (HTML)."""
    text = html.escape(str(path))
    return text.replace("\\", "\\\u200b").replace("/", "/\u200b")


def connection_text(spec: Optional[ConnectionSpec]) -> str:
    if spec is None:
        return "no connection"
    kind = KIND_TITLES.get(spec.kind, spec.kind)
    where = spec.host or spec.serial_port or spec.resource or ""
    if spec.port and spec.host:
        where += f":{spec.port}"
    if spec.gpib is not None:
        where += f" GPIB {spec.gpib}"
    return f"{kind} {where}".strip()


class ConnectionEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.kind = QComboBox()
        for kind in KINDS:
            self.kind.addItem(KIND_TITLES.get(kind, kind), kind)
        self.host = QLineEdit()
        self.host.setPlaceholderText("169.254.0.1")
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText("default")
        self.serial_port = QLineEdit()
        self.serial_port.setPlaceholderText("COM3 or /dev/ttyUSB0")
        self.gpib = QSpinBox()
        self.gpib.setRange(0, 30)
        self.resource = QLineEdit()
        self.resource.setPlaceholderText("GPIB0::19::INSTR")
        self.baudrate = QComboBox()
        for rate in (9600, 19200, 38400, 57600, 115200):
            self.baudrate.addItem(str(rate), rate)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(0.1, 600)
        self.timeout.setSuffix(" s")
        self.read_delay = QDoubleSpinBox()
        self.read_delay.setRange(0, 10)
        self.read_delay.setDecimals(3)
        self.read_delay.setSuffix(" s")
        self.rows = {}
        self.form.addRow("Adapter", self.kind)
        for name, title in (
            ("host", "Host"), ("port", "Port"), ("serial_port", "Serial port"),
            ("gpib", "GPIB address"), ("resource", "VISA resource"),
            ("baudrate", "Baud rate"), ("timeout", "Timeout"), ("read_delay", "Read delay"),
        ):  # fmt: skip
            label = QLabel(title)
            self.form.addRow(label, getattr(self, name))
            self.rows[name] = label
        self.kind.currentIndexChanged.connect(self.update_rows)
        self.base: Optional[ConnectionSpec] = None
        self.set_spec(None)

    def update_rows(self) -> None:
        used = CONNECTION_FIELDS.get(self.kind.currentData(), ())
        for name, label in self.rows.items():
            label.setVisible(name in used)
            getattr(self, name).setVisible(name in used)

    def set_spec(self, spec: Optional[ConnectionSpec]) -> None:
        self.base = spec
        if spec is None:
            self.kind.setCurrentIndex(self.kind.findData(SOCKET))
            for line in (self.host, self.serial_port, self.resource):
                line.clear()
            self.port.setValue(0)
            self.timeout.setValue(2.0)
            self.read_delay.setValue(0.0)
            self.update_rows()
            return
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec.kind)))
        self.host.setText(spec.host or "")
        self.port.setValue(spec.port or 0)
        self.serial_port.setText(spec.serial_port or "")
        self.gpib.setValue(spec.gpib or 0)
        self.resource.setText(spec.resource or "")
        self.baudrate.setCurrentIndex(max(0, self.baudrate.findData(spec.baudrate)))
        self.timeout.setValue(spec.timeout)
        self.read_delay.setValue(spec.read_delay)
        self.update_rows()

    def spec(self) -> ConnectionSpec:
        kind = self.kind.currentData()
        used = CONNECTION_FIELDS.get(kind, ())
        values = {
            "host": self.host.text().strip() or None,
            "port": self.port.value() or None,
            "serial_port": self.serial_port.text().strip() or None,
            "gpib": self.gpib.value(),
            "resource": self.resource.text().strip() or None,
            "baudrate": self.baudrate.currentData(),
            "timeout": self.timeout.value(),
            "read_delay": self.read_delay.value(),
        }
        fields = {k: v for k, v in values.items() if k in used}
        # Terminations and other details stay as the driver recommended them
        keep = {}
        if self.base is not None:
            keep = {
                "write_termination": self.base.write_termination,
                "read_termination": self.base.read_termination,
            }
        return ConnectionSpec(kind, **fields, **keep)


class InstrumentDialog(QDialog):
    """Add or edit an instrument: driver, name, connection."""

    def __init__(
        self, config: StationConfig, instrument_id: Optional[str] = None, parent=None
    ):
        super().__init__(parent)
        self.config = config
        self.instrument_id = instrument_id
        editing = instrument_id is not None
        spec = config.instruments.get(instrument_id) if editing else None
        self.setWindowTitle("Edit instrument" if editing else "Add instrument")
        self.setWindowIcon(theme.icon("chip"))
        self.registry = default_registry()
        form = QFormLayout()
        self.driver = QComboBox()
        # Real drivers only: simulation is the checkbox below (or --simulate)
        for info in sorted(self.registry.all(), key=lambda i: i.title):
            if not info.simulated:
                self.driver.addItem(info.title, info.key)
        if spec is not None and self.driver.findData(spec.driver) < 0:
            # A driver no longer offered (Pfeiffer, a simulator): keep it as it is
            title = (
                self.registry.get(spec.driver).title
                if spec.driver in self.registry
                else spec.driver
            )
            self.driver.addItem(title, spec.driver)
        self.title = QLineEdit()
        self.title.setPlaceholderText("shown in menus and docks")
        self.ident = QLabel()
        self.ident.setProperty("role", "muted")
        self.simulate = QCheckBox("Always simulate this instrument")
        self.connection = ConnectionEditor()
        self.recommended = QPushButton("Recommended connection")
        self.recommended.clicked.connect(self.fill_recommended)
        form.addRow("Driver", self.driver)
        form.addRow("Name", self.title)
        form.addRow("Id", self.ident)
        form.addRow("", self.simulate)
        box = QGroupBox("Connection")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self.connection)
        box_layout.addWidget(self.recommended, 0, Qt.AlignRight)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_values)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(box)
        layout.addWidget(buttons)
        self.driver.currentIndexChanged.connect(self.driver_changed)
        if spec is not None:
            self.driver.setCurrentIndex(max(0, self.driver.findData(spec.driver)))
            self.driver.setEnabled(
                False
            )  # devices depend on it; delete and add instead
            self.title.setText(spec.title)
            self.simulate.setChecked(spec.simulate)
            self.connection.set_spec(spec.connection)
            self.ident.setText(instrument_id)
        else:
            self.driver_changed()

    def driver_key(self) -> str:
        return self.driver.currentData()

    def accept_values(self) -> None:
        try:
            self.instrument()
        except ConfigurationError as e:
            QMessageBox.warning(self, "Connection", str(e))
            return
        self.accept()

    def driver_changed(self) -> None:
        if self.instrument_id is not None:
            return
        key = self.driver_key()
        self.ident.setText(self.config.next_id(instrument_type(key)))
        info = self.registry.get(key)
        self.title.setPlaceholderText(info.title)
        self.fill_recommended()

    def fill_recommended(self) -> None:
        if self.driver_key() not in self.registry:
            return
        cls = self.registry.get(self.driver_key()).cls
        factory = getattr(cls, "connection", None)
        if callable(factory):
            try:
                self.connection.set_spec(factory())
            except TypeError:
                pass

    def instrument(self) -> InstrumentConfig:
        old = self.config.instruments.get(self.instrument_id)
        key = self.driver_key()
        info = self.registry.get(key) if key in self.registry else None
        simulated = info is not None and info.simulated
        spec = copy.deepcopy(old) if old else InstrumentConfig(key)
        spec.title = self.title.text().strip() or (info.title if info else key)
        spec.simulate = self.simulate.isChecked() or simulated
        spec.connection = None if simulated else self.connection.spec()
        return spec

    def new_id(self) -> str:
        return self.instrument_id or self.ident.text()


class DeviceDialog(QDialog):
    """Add or edit a device on an instrument: kind, channel, name, settings."""

    def __init__(self, station, instrument_id: str, device_id=None, parent=None):
        super().__init__(parent)
        self.station = station
        self.instrument_id = instrument_id
        self.device_id = device_id
        config = station.config
        spec = config.instruments[instrument_id].devices.get(device_id)
        self.setWindowTitle("Edit device" if spec else "Add device")
        self.kinds = station.kinds(instrument_id)
        form = QFormLayout()
        self.kind = QComboBox()
        for key, kind in self.kinds.items():
            self.kind.addItem(theme.device_icon(key), kind.title, key)
        self.channel = QComboBox()
        self.channel_label = QLabel("Channel")
        self.title = QLineEdit()
        self.ident = QLabel()
        self.ident.setProperty("role", "muted")
        form.addRow("Kind", self.kind)
        form.addRow(self.channel_label, self.channel)
        form.addRow("Name", self.title)
        form.addRow("Id", self.ident)
        self.settings_box = QGroupBox("Settings")
        self.settings = ParameterForm()
        QVBoxLayout(self.settings_box).addWidget(self.settings)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_values)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.settings_box)
        layout.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self.kind_changed)
        if spec is not None:
            self.kind.setCurrentIndex(max(0, self.kind.findData(spec.kind)))
            self.kind.setEnabled(False)
            self.kind_changed()
            self.channel.setCurrentIndex(max(0, self.channel.findData(spec.channel)))
            self.title.setText(spec.title)
            self.settings.set_values(spec.settings)
            self.ident.setText(device_id)
        else:
            self.kind_changed()
        self.metadata = dict(spec.metadata) if spec else {}

    def kind_changed(self) -> None:
        key = self.kind.currentData()
        kind = self.kinds.get(key)
        if kind is None:
            return
        self.channel.clear()
        for channel in kind.keys:
            self.channel.addItem(str(channel), channel)
        self.channel.setVisible(bool(kind.keys))
        self.channel_label.setVisible(bool(kind.keys))
        self.settings.set_parameters({p.name: p for p in kind.settings})
        self.settings_box.setVisible(bool(kind.settings))
        if self.device_id is None:
            self.ident.setText(self.station.config.next_id(key))

    def accept_values(self) -> None:
        try:
            self.settings.values()
        except ProcedureError as e:
            QMessageBox.warning(self, "Device settings", str(e))
            return
        self.accept()

    def device(self) -> DeviceConfig:
        key = self.kind.currentData()
        kind = self.kinds[key]
        title = self.title.text().strip()
        channel = self.channel.currentData() if kind.keys else None
        if not title:
            host = self.station.config.instruments[self.instrument_id].title
            title = f"{kind.title} {channel}" if channel is not None else kind.title
            title = f"{host} {title}" if host else title
        return DeviceConfig(
            kind=key,
            channel=channel,
            title=title,
            settings=self.settings.values(),
            metadata=self.metadata,
        )

    def new_id(self) -> str:
        return self.device_id or self.ident.text()


def compact_button(icon_name: str, text: str) -> QToolButton:
    button = QToolButton()
    button.setIcon(theme.icon(icon_name))
    button.setText(text)
    button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    return button


class InstrumentCard(QGroupBox):
    connect_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    add_device_requested = Signal(str)
    edit_device_requested = Signal(str, str)
    delete_device_requested = Signal(str, str)

    def __init__(self, station, instrument_id: str, parent=None):
        super().__init__(parent)
        self.instrument_id = instrument_id
        spec = station.config.instruments[instrument_id]
        self.search_text = f"{spec.title} {instrument_id} {spec.driver}".lower()
        self.setTitle(spec.title or instrument_id)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        info = (
            default_registry().get(spec.driver)
            if spec.driver in default_registry()
            else None
        )
        driver = QLabel(info.title if info else spec.driver)
        where = QLabel(
            connection_text(spec.connection) + ("  [sim]" if spec.simulate else "")
        )
        where.setWordWrap(True)
        ident = QLabel(instrument_id)
        ident.setProperty("role", "muted")
        self.status = QLabel("not connected")
        self.status.setWordWrap(True)
        form.addRow("Driver", driver)
        form.addRow("Connection", where)
        form.addRow("Id", ident)
        form.addRow("Status", self.status)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for text, icon_name, signal in (
            ("Connect", "lan-connect", self.connect_requested),
            ("Edit", "pencil-outline", self.edit_requested),
            ("Delete", "delete-outline", self.delete_requested),
        ):
            button = compact_button(icon_name, text)
            button.clicked.connect(lambda _=False, s=signal: s.emit(self.instrument_id))
            buttons.addWidget(button)
        kinds = {}
        try:
            kinds = station.kinds(instrument_id)
        except InstrumentError:
            pass
        if kinds:
            add = compact_button("plus", "Add device")
            add.setToolTip(", ".join(k.title for k in kinds.values()))
            add.clicked.connect(
                lambda: self.add_device_requested.emit(self.instrument_id)
            )
            buttons.addWidget(add)
        buttons.addStretch()
        layout.addLayout(buttons)
        for device_id, device in spec.devices.items():
            row = QHBoxLayout()
            icon = QLabel()
            icon.setPixmap(theme.device_icon(device.kind).pixmap(16, 16))
            channel = f" {device.channel}" if device.channel is not None else ""
            label = QLabel(
                f"{device.title or device_id}  <span style='color:{theme.MUTED}'>"
                f"{device.kind}{channel} · {device_id}</span>"
            )
            label.setWordWrap(True)
            row.addWidget(icon)
            row.addWidget(label, 1)
            for icon_name, tip, signal in (
                ("pencil-outline", "Edit device", self.edit_device_requested),
                ("delete-outline", "Delete device", self.delete_device_requested),
            ):
                tool = QToolButton()
                tool.setIcon(theme.icon(icon_name))
                tool.setToolTip(tip)
                tool.clicked.connect(
                    lambda _=False, s=signal, d=device_id: s.emit(self.instrument_id, d)
                )
                row.addWidget(tool)
            self.search_text += f" {device.title} {device_id}".lower()
            layout.addLayout(row)

    def set_status(self, text: str, ok: bool) -> None:
        color = "#81c784" if ok else "#e57373"
        self.status.setText(textwrap.shorten(text, width=60, placeholder="..."))
        self.status.setToolTip(text)
        self.status.setStyleSheet(f"color: {color}")


class ConnectionsGroup(QGroupBox):
    """Shared connections (a Prologix, a single-client socket) with their state.

    Reset breaks a command that hangs on the connection and reconnects; the
    instruments on it go on with the next command.
    """

    def __init__(self, station, parent=None):
        super().__init__("Connections", parent)
        self.station = station
        self.rows: Dict[tuple, QLabel] = {}
        self.resetting = set()
        self.jobs = []
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        note = QLabel("Shared by the instruments listed; Reset if one hangs")
        note.setProperty("role", "muted")
        refresh = QToolButton()
        refresh.setIcon(theme.icon("refresh"))
        refresh.setToolTip("Refresh the state")
        refresh.clicked.connect(self.refresh)
        header.addWidget(note, 1)
        header.addWidget(refresh)
        layout.addLayout(header)
        for connection in station.connections():
            row = QHBoxLayout()
            label = QLabel(
                f"<b>{connection.label}</b><br><span style='color:{theme.MUTED}'>"
                f"{', '.join(connection.instruments)}</span>"
            )
            label.setWordWrap(True)
            state = QLabel()
            reset = compact_button("restart", "Reset")
            reset.clicked.connect(lambda _=False, k=connection.key: self.reset(k))
            row.addWidget(label, 1)
            row.addWidget(state)
            row.addWidget(reset)
            layout.addLayout(row)
            self.rows[connection.key] = state
        self.refresh()
        # A link breaks or reconnects under measurements and monitors too
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)

    def refresh(self) -> None:
        for connection in self.station.connections():
            state = self.rows.get(connection.key)
            if state is None or connection.key in self.resetting:
                continue
            if connection.broken:
                text, color = "error, reconnects", "#e57373"
            elif connection.open:
                text, color = "connected", "#81c784"
            else:
                text, color = "not connected", theme.MUTED
            state.setText(text)
            state.setStyleSheet(f"color: {color}")

    def reset(self, key: tuple) -> None:
        from thzdaq_gui.update_dialog import Background

        self.rows[key].setText("resetting...")
        self.resetting.add(key)
        station = self.station

        def job(_task):
            # Abort first: a command blocked on the link holds its lock
            station.transport_pool.abort(key)
            return station.reset_connection(key)

        def done(_):
            self.resetting.discard(key)
            self.refresh()

        def failed(message):
            self.resetting.discard(key)
            self.rows[key].setText(f"failed: {message}")

        task = Background(job, self)
        task.done.connect(done)
        task.failed.connect(failed)
        self.jobs.append(task)
        task.start()


class SetupWidget(QWidget):
    """Profile, saved instruments and their devices."""

    open_profile_requested = Signal()
    new_profile_requested = Signal()

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.cards: Dict[str, InstrumentCard] = {}
        self.statuses: Dict[str, tuple] = {}
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.profile = QLabel()
        self.profile.setWordWrap(True)
        open_button = QToolButton()
        open_button.setIcon(theme.icon("folder-open-outline"))
        open_button.setToolTip("Open station profile")
        open_button.clicked.connect(self.open_profile_requested)
        new_button = QToolButton()
        new_button.setIcon(theme.icon("file-plus-outline"))
        new_button.setToolTip("New station profile")
        new_button.clicked.connect(self.new_profile_requested)
        header.addWidget(self.profile, 1)
        header.addWidget(open_button)
        header.addWidget(new_button)
        layout.addLayout(header)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search device")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        layout.addWidget(self.search)
        self.btnAdd = QPushButton(theme.icon("plus", "#111111"), "Add instrument")
        self.btnAdd.setProperty("accent", True)
        self.btnAdd.clicked.connect(self.add_instrument)
        layout.addWidget(self.btnAdd)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll, 1)
        session.station_changed.connect(self.rebuild)
        session.config_changed.connect(self.rebuild)
        self.rebuild()

    # Building
    def rebuild(self, *_) -> None:
        station = self.session.station
        path = self.session.path
        self.profile.setText(
            f"<b>{station.name}</b><br>"
            f"<span style='color:{theme.MUTED}'>{breakable_path(path)}</span>"
            if station is not None
            else "No station profile"
        )
        self.profile.setToolTip(str(path) if path else "")
        self.btnAdd.setEnabled(station is not None)
        container = QWidget()
        column = QVBoxLayout(container)
        self.cards = {}
        self.connections = None
        if station is not None and station.connections():
            self.connections = ConnectionsGroup(station)
            column.addWidget(self.connections)
        if station is not None:
            for instrument_id in station.config.instruments:
                card = InstrumentCard(station, instrument_id)
                card.connect_requested.connect(self.connect_instrument)
                card.edit_requested.connect(self.edit_instrument)
                card.delete_requested.connect(self.delete_instrument)
                card.add_device_requested.connect(self.add_device)
                card.edit_device_requested.connect(self.edit_device)
                card.delete_device_requested.connect(self.delete_device)
                if instrument_id in self.statuses:
                    card.set_status(*self.statuses[instrument_id])
                column.addWidget(card)
                self.cards[instrument_id] = card
        column.addStretch()
        self.scroll.setWidget(container)
        self.filter(self.search.text())

    def filter(self, text: str) -> None:
        text = text.lower().strip()
        for card in self.cards.values():
            card.setVisible(not text or text in card.search_text)

    # Editing
    def _edited(self) -> Optional[StationConfig]:
        if self.session.station is None:
            return None
        return copy.deepcopy(self.session.station.config)

    def _apply(self, config: StationConfig) -> bool:
        try:
            self.session.update_config(config)
        except (StationError, OSError) as e:
            QMessageBox.critical(self, "Station profile", str(e))
            return False
        return True

    def add_instrument(self) -> None:
        config = self._edited()
        if config is None:
            return
        dialog = InstrumentDialog(config, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        config.instruments[dialog.new_id()] = dialog.instrument()
        self._apply(config)

    def edit_instrument(self, instrument_id: str) -> None:
        config = self._edited()
        dialog = InstrumentDialog(config, instrument_id, self)
        if dialog.exec() != QDialog.Accepted:
            return
        config.instruments[instrument_id] = dialog.instrument()
        self.statuses.pop(instrument_id, None)
        self._apply(config)

    def delete_instrument(self, instrument_id: str) -> None:
        config = self._edited()
        spec = config.instruments[instrument_id]
        devices = len(spec.devices)
        extra = f" and its {devices} device(s)" if devices else ""
        answer = QMessageBox.question(
            self,
            "Delete instrument",
            f"Delete '{spec.title or instrument_id}'{extra}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        del config.instruments[instrument_id]
        self.statuses.pop(instrument_id, None)
        self._apply(config)

    def add_device(self, instrument_id: str) -> None:
        dialog = DeviceDialog(self.session.station, instrument_id, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        config = self._edited()
        config.instruments[instrument_id].devices[dialog.new_id()] = dialog.device()
        self._apply(config)

    def edit_device(self, instrument_id: str, device_id: str) -> None:
        dialog = DeviceDialog(self.session.station, instrument_id, device_id, self)
        if dialog.exec() != QDialog.Accepted:
            return
        config = self._edited()
        config.instruments[instrument_id].devices[device_id] = dialog.device()
        self._apply(config)

    def delete_device(self, instrument_id: str, device_id: str) -> None:
        config = self._edited()
        device = config.instruments[instrument_id].devices[device_id]
        answer = QMessageBox.question(
            self,
            "Delete device",
            f"Delete '{device.title or device_id}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            del config.instruments[instrument_id].devices[device_id]
            self._apply(config)

    # Connecting
    def connect_instrument(self, instrument_id: str) -> None:
        station = self.session.station
        card = self.cards.get(instrument_id)
        if station is None or card is None:
            return
        card.status.setText("connecting...")

        def job():
            instrument = station.instrument(instrument_id)
            identify = getattr(instrument, "identify", None)
            return identify() if callable(identify) else "opened"

        def done(identity):
            if self.connections is not None:
                self.connections.refresh()
            self.statuses[instrument_id] = (f"OK: {identity}", True)
            if instrument_id in self.cards:
                self.cards[instrument_id].set_status(f"OK: {identity}", True)

        def failed(error):
            text = f"{error.__class__.__name__}: {error}"
            self.statuses[instrument_id] = (text, False)
            if instrument_id in self.cards:
                self.cards[instrument_id].set_status(text, False)

        title = station.config.instruments[instrument_id].title or instrument_id
        self.session.worker.submit(job, done, failed, title)


def ask_profile_path(parent, save: bool) -> Optional[str]:
    folder = str(stations_dir())
    if save:
        path, _ = QFileDialog.getSaveFileName(
            parent, "New station profile", folder, "YAML (*.yaml)"
        )
    else:
        path, _ = QFileDialog.getOpenFileName(
            parent, "Open station profile", folder, "YAML (*.yaml *.yml)"
        )
    return path or None
