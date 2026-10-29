"""Setup dock: the saved instruments, as in the old app, plus their devices.

Every instrument is a card: driver, connection, status and the devices it
hosts (SIS bias and coil). Add / Edit / Delete change the station profile
through the lab, which checks and saves it at once; device docks follow.
"""

import html
import textwrap
from typing import Any, Callable, Dict, Optional, Sequence

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
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
from thzdaq_api.errors import LabError
from thzdaq_api.station import (
    ConnectInstrument,
    ConnectionKindInfo,
    DriverInfo,
    ListConnections,
    ResetConnection,
)

from thzdaq_gui import profile as fmt
from thzdaq_gui import theme
from thzdaq_gui.forms import ParameterForm
from thzdaq_gui.wording import NEW_PROFILE, OPEN_PROFILE, STATION_PROFILE

# How often the Connections group shows the state of the links
REFRESH_MS = 2000

# Saves an entry (new id, entry) into the profile; LabError when the lab refuses
Save = Callable[[str, Dict[str, Any]], None]


def breakable_path(path) -> str:
    """A path a word-wrapped label may break after any separator (HTML)."""
    text = html.escape(str(path))
    return text.replace("\\", "\\\u200b").replace("/", "/\u200b")


def connection_text(
    connection: Optional[Dict[str, Any]], kinds: Sequence[ConnectionKindInfo]
) -> str:
    if not connection:
        return "no connection"
    kind = connection.get(fmt.KIND, "")
    title = next((k.title for k in kinds if k.key == kind), kind)
    where = (
        connection.get("host")
        or connection.get("serial_port")
        or connection.get("resource")
        or ""
    )
    if connection.get("port") and connection.get("host"):
        where += f":{connection['port']}"
    if connection.get("gpib") is not None:
        where += f" GPIB {connection['gpib']}"
    return f"{title} {where}".strip()


class ConnectionEditor(QWidget):
    """A connection of the profile: its kind, and the fields that kind uses."""

    # Details the editor does not show, kept as they were (the driver's)
    KEPT = ("write_termination", "read_termination")

    def __init__(self, kinds: Sequence[ConnectionKindInfo], parent=None):
        super().__init__(parent)
        self.kinds = {kind.key: kind for kind in kinds}
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.kind = QComboBox()
        for kind in kinds:
            self.kind.addItem(kind.title, kind.key)
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
        self.base: Dict[str, Any] = {}
        self.set_spec(None)

    def fields(self) -> Sequence[str]:
        kind = self.kinds.get(self.kind.currentData())
        return kind.fields if kind is not None else ()

    def update_rows(self) -> None:
        used = self.fields()
        for name, label in self.rows.items():
            label.setVisible(name in used)
            getattr(self, name).setVisible(name in used)

    def set_spec(self, connection: Optional[Dict[str, Any]]) -> None:
        """Show a connection of the profile; None: an empty one of the first kind."""
        self.base = dict(connection or {})
        index = self.kind.findData(self.base.get(fmt.KIND))
        self.kind.setCurrentIndex(max(0, index))
        kind = self.kinds[self.kind.currentData()]
        value = {**kind.defaults, **self.base}.get
        self.host.setText(value("host") or "")
        self.port.setValue(value("port") or 0)
        self.serial_port.setText(value("serial_port") or "")
        self.gpib.setValue(value("gpib") or 0)
        self.resource.setText(value("resource") or "")
        self.baudrate.setCurrentIndex(max(0, self.baudrate.findData(value("baudrate"))))
        self.timeout.setValue(value("timeout") or self.timeout.minimum())
        self.read_delay.setValue(value("read_delay") or 0.0)
        self.update_rows()

    def spec(self) -> Dict[str, Any]:
        """The connection as the profile holds it; the lab checks it."""
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
        used = self.fields()
        kept = {k: self.base[k] for k in self.KEPT if k in self.base}
        return {
            fmt.KIND: self.kind.currentData(),
            **{k: v for k, v in values.items() if k in used and v is not None},
            **kept,
        }


def saved_or_told(dialog: QDialog, title: str, save: Callable[[], None]) -> None:
    """Save and close; a refusal of the lab is told and the dialog stays."""
    try:
        save()
    except LabError as e:
        QMessageBox.warning(dialog, title, str(e))
        return
    dialog.accept()


class InstrumentDialog(QDialog):
    """Add or edit an instrument: driver, name, connection. Save puts it into
    the profile; the dialog stays open while the lab refuses it."""

    def __init__(
        self, session, save: Save, instrument_id: Optional[str] = None, parent=None
    ):
        super().__init__(parent)
        self.session = session
        self.save = save
        self.instrument_id = instrument_id
        profile = session.profile().profile
        self.profile = profile
        editing = instrument_id is not None
        spec = fmt.instruments(profile).get(instrument_id, {}) if editing else {}
        self.spec = spec
        self.setWindowTitle("Edit instrument" if editing else "Add instrument")
        self.setWindowIcon(theme.icon("chip"))
        self.drivers = session.drivers()
        form = QFormLayout()
        self.driver = QComboBox()
        # Real drivers only: simulation is the checkbox below (or --simulate)
        for info in sorted(self.drivers.values(), key=lambda i: i.title):
            if not info.simulated:
                self.driver.addItem(info.title, info.key)
        driver = spec.get(fmt.DRIVER)
        if driver is not None and self.driver.findData(driver) < 0:
            # A driver no longer offered (Pfeiffer, a simulator): keep it as it is
            known = self.drivers.get(driver)
            self.driver.addItem(known.title if known else driver, driver)
        self.title = QLineEdit()
        self.title.setPlaceholderText("shown in menus and docks")
        self.ident = QLabel()
        self.ident.setProperty("role", "muted")
        self.simulate = QCheckBox("Always simulate this instrument")
        self.connection = ConnectionEditor(session.connection_kinds())
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
        if editing:
            self.driver.setCurrentIndex(max(0, self.driver.findData(driver)))
            # Devices depend on the driver; delete and add instead
            self.driver.setEnabled(False)
            self.title.setText(spec.get(fmt.TITLE, ""))
            self.simulate.setChecked(bool(spec.get(fmt.SIMULATE)))
            self.connection.set_spec(spec.get(fmt.CONNECTION))
            self.ident.setText(instrument_id)
        else:
            self.driver_changed()

    def driver_key(self) -> str:
        return self.driver.currentData()

    def driver_info(self) -> Optional[DriverInfo]:
        return self.drivers.get(self.driver_key())

    def accept_values(self) -> None:
        saved_or_told(
            self, "Instrument", lambda: self.save(self.new_id(), self.instrument())
        )

    def driver_changed(self) -> None:
        if self.instrument_id is not None:
            return
        info = self.driver_info()
        self.ident.setText(fmt.next_id(self.profile, info.type))
        self.title.setPlaceholderText(info.title)
        self.fill_recommended()

    def fill_recommended(self) -> None:
        info = self.driver_info()
        if info is not None and info.connection is not None:
            self.connection.set_spec(info.connection)

    def instrument(self) -> Dict[str, Any]:
        """The entry of the profile, with what the dialog does not show kept."""
        info = self.driver_info()
        simulated = info is not None and info.simulated
        entry = {**self.spec, fmt.DRIVER: self.driver_key()}
        entry[fmt.TITLE] = self.title.text().strip() or (
            info.title if info else self.driver_key()
        )
        entry[fmt.SIMULATE] = self.simulate.isChecked() or simulated
        entry[fmt.CONNECTION] = None if simulated else self.connection.spec()
        return entry

    def new_id(self) -> str:
        return self.instrument_id or self.ident.text()


class DeviceDialog(QDialog):
    """Add or edit a device on an instrument: kind, channel, name, settings. Save
    puts it into the profile; the dialog stays open while the lab refuses it."""

    def __init__(
        self, session, save: Save, instrument_id: str, device_id=None, parent=None
    ):
        super().__init__(parent)
        self.save = save
        self.instrument_id = instrument_id
        self.device_id = device_id
        self.profile = session.profile().profile
        instrument = fmt.instruments(self.profile)[instrument_id]
        self.host = instrument.get(fmt.TITLE, "")
        spec = fmt.devices(instrument).get(device_id)
        self.spec = dict(spec or {})
        self.setWindowTitle("Edit device" if spec else "Add device")
        driver = session.drivers().get(instrument[fmt.DRIVER])
        self.kinds = {kind.key: kind for kind in (driver.kinds if driver else ())}
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
            self.kind.setCurrentIndex(max(0, self.kind.findData(spec.get(fmt.KIND))))
            self.kind.setEnabled(False)
            self.kind_changed()
            self.channel.setCurrentIndex(
                max(0, self.channel.findData(spec.get(fmt.CHANNEL)))
            )
            self.title.setText(spec.get(fmt.TITLE, ""))
            self.settings.set_values(spec.get(fmt.SETTINGS) or {})
            self.ident.setText(device_id)
        else:
            self.kind_changed()

    def kind_changed(self) -> None:
        kind = self.kinds.get(self.kind.currentData())
        if kind is None:
            return
        self.channel.clear()
        for channel in kind.channels:
            self.channel.addItem(channel, channel)
        self.channel.setVisible(bool(kind.channels))
        self.channel_label.setVisible(bool(kind.channels))
        self.settings.set_parameters(kind.settings)
        self.settings_box.setVisible(bool(kind.settings))
        if self.device_id is None:
            self.ident.setText(fmt.next_id(self.profile, kind.key))

    def accept_values(self) -> None:
        saved_or_told(
            self, "Device settings", lambda: self.save(self.new_id(), self.device())
        )

    def device(self) -> Dict[str, Any]:
        """The entry of the profile; raises ValueError for settings that are not numbers."""
        kind = self.kinds[self.kind.currentData()]
        title = self.title.text().strip()
        channel = self.channel.currentData() if kind.channels else None
        if not title:
            title = f"{kind.title} {channel}" if channel is not None else kind.title
            title = f"{self.host} {title}" if self.host else title
        return {
            **self.spec,
            fmt.KIND: kind.key,
            fmt.CHANNEL: channel,
            fmt.TITLE: title,
            fmt.SETTINGS: self.settings.values(),
        }

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

    def __init__(self, session, instrument_id: str, spec: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.instrument_id = instrument_id
        driver_key = spec.get(fmt.DRIVER, "")
        title = spec.get(fmt.TITLE, "")
        self.search_text = f"{title} {instrument_id} {driver_key}".lower()
        self.setTitle(title or instrument_id)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        info = session.drivers().get(driver_key)
        driver = QLabel(info.title if info else driver_key)
        where = QLabel(
            connection_text(spec.get(fmt.CONNECTION), session.connection_kinds())
            + ("  [sim]" if spec.get(fmt.SIMULATE) else "")
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
        kinds = info.kinds if info else ()
        if kinds:
            add = compact_button("plus", "Add device")
            add.setToolTip(", ".join(k.title for k in kinds))
            add.clicked.connect(
                lambda: self.add_device_requested.emit(self.instrument_id)
            )
            buttons.addWidget(add)
        buttons.addStretch()
        layout.addLayout(buttons)
        for device_id, device in fmt.devices(spec).items():
            row = QHBoxLayout()
            icon = QLabel()
            kind = device.get(fmt.KIND, "")
            icon.setPixmap(theme.device_icon(kind).pixmap(16, 16))
            channel = device.get(fmt.CHANNEL)
            channel = f" {channel}" if channel is not None else ""
            device_title = device.get(fmt.TITLE, "")
            label = QLabel(
                f"{device_title or device_id}  <span style='color:{theme.MUTED}'>"
                f"{kind}{channel} · {device_id}</span>"
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
            self.search_text += f" {device_title} {device_id}".lower()
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

    def __init__(self, session, parent=None):
        super().__init__("Connections", parent)
        self.session = session
        self.rows: Dict[tuple, QLabel] = {}
        self.resetting = set()
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
        for connection in session.call(ListConnections()):
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
        for connection in self.session.call(ListConnections()):
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
        self.rows[key].setText("resetting...")
        self.resetting.add(key)
        lab, reset = self.session.lab, ResetConnection(key=key)

        def done(_):
            self.resetting.discard(key)
            self.refresh()

        def failed(error):
            self.resetting.discard(key)
            self.rows[key].setText(f"failed: {error}")

        # A queue of its own: not behind a command that hangs on the link
        self.session.calls.submit(
            lambda: lab.call(reset), done, failed, str(key), key=f"reset {key}"
        )


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
        open_button.setToolTip(OPEN_PROFILE)
        open_button.clicked.connect(self.open_profile_requested)
        new_button = QToolButton()
        new_button.setIcon(theme.icon("file-plus-outline"))
        new_button.setToolTip(NEW_PROFILE)
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
        station = self.session.profile()
        loaded = station.path is not None
        self.profile.setText(
            f"<b>{station.name}</b><br>"
            f"<span style='color:{theme.MUTED}'>{breakable_path(station.path)}</span>"
            if loaded
            else "No station profile"
        )
        self.profile.setToolTip(station.path or "")
        self.btnAdd.setEnabled(loaded)
        container = QWidget()
        column = QVBoxLayout(container)
        self.cards = {}
        self.connections = None
        if self.session.call(ListConnections()):
            self.connections = ConnectionsGroup(self.session)
            column.addWidget(self.connections)
        for instrument_id, spec in fmt.instruments(station.profile).items():
            card = InstrumentCard(self.session, instrument_id, spec)
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

    # Editing: a changed copy of the profile goes to the lab
    def edited(self) -> Dict[str, Any]:
        return fmt.changed(self.session.profile().profile)

    def apply(self, profile: Dict[str, Any]) -> None:
        """Hand the profile to the lab; a refusal is told here."""
        try:
            self.session.update_profile(profile)
        except LabError as e:
            QMessageBox.critical(self, STATION_PROFILE, str(e))

    def save_instrument(self, instrument_id: str, entry: Dict[str, Any]) -> None:
        profile = self.edited()
        fmt.instruments(profile)[instrument_id] = entry
        self.statuses.pop(instrument_id, None)
        self.session.update_profile(profile)

    def device_saver(self, instrument_id: str) -> Save:
        def save(device_id: str, entry: Dict[str, Any]) -> None:
            profile = self.edited()
            fmt.devices(fmt.instruments(profile)[instrument_id])[device_id] = entry
            self.session.update_profile(profile)

        return save

    def add_instrument(self) -> None:
        InstrumentDialog(self.session, self.save_instrument, parent=self).exec()

    def edit_instrument(self, instrument_id: str) -> None:
        InstrumentDialog(self.session, self.save_instrument, instrument_id, self).exec()

    def delete_instrument(self, instrument_id: str) -> None:
        profile = self.edited()
        spec = fmt.instruments(profile)[instrument_id]
        count = len(fmt.devices(spec))
        extra = f" and its {count} device(s)" if count else ""
        answer = QMessageBox.question(
            self,
            "Delete instrument",
            f"Delete '{spec.get(fmt.TITLE) or instrument_id}'{extra}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        del fmt.instruments(profile)[instrument_id]
        self.statuses.pop(instrument_id, None)
        self.apply(profile)

    def add_device(self, instrument_id: str) -> None:
        save = self.device_saver(instrument_id)
        DeviceDialog(self.session, save, instrument_id, parent=self).exec()

    def edit_device(self, instrument_id: str, device_id: str) -> None:
        save = self.device_saver(instrument_id)
        DeviceDialog(self.session, save, instrument_id, device_id, self).exec()

    def delete_device(self, instrument_id: str, device_id: str) -> None:
        profile = self.edited()
        devices = fmt.devices(fmt.instruments(profile)[instrument_id])
        title = devices[device_id].get(fmt.TITLE) or device_id
        answer = QMessageBox.question(
            self,
            "Delete device",
            f"Delete '{title}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            del devices[device_id]
            self.apply(profile)

    # Connecting
    def connect_instrument(self, instrument_id: str) -> None:
        card = self.cards.get(instrument_id)
        if card is None:
            return
        card.status.setText("connecting...")
        lab, connect = self.session.lab, ConnectInstrument(instrument=instrument_id)

        def done(identity):
            if self.connections is not None:
                self.connections.refresh()
            self.tell(instrument_id, f"OK: {identity}", True)

        def failed(error):
            self.tell(instrument_id, str(error), False)

        self.session.calls.submit(
            lambda: lab.call(connect), done, failed, card.title(), key=instrument_id
        )

    def tell(self, instrument_id: str, text: str, ok: bool) -> None:
        """How connecting went, kept for the card after a rebuild."""
        self.statuses[instrument_id] = (text, ok)
        if instrument_id in self.cards:
            self.cards[instrument_id].set_status(text, ok)
