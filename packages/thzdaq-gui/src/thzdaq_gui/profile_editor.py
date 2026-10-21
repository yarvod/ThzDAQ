"""Editor of a station profile: instruments and roles tables plus raw YAML."""

from typing import Any, Dict, List, Optional

import yaml
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.errors import StationError
from thzdaq_core.station.config import StationConfig
from thzdaq_core.station.ports import ADAPTERS
from thzdaq_core.station.storage import (
    ProfileLoader,
    dump_station,
    save_station,
    station_from_dict,
    station_to_dict,
)
from thzdaq_instruments import default_registry

INSTRUMENT_WIDTHS = (150, 170, 420, 220, 70, 200)
ROLE_WIDTHS = (120, 170, 80, 80, 170, 220, 330)
INSTRUMENT_COLUMNS = (
    "Id", "Driver", "Connection", "Options", "Simulate", "Sim options", "Title",
)  # fmt: skip
ROLE_COLUMNS = (
    "Role", "Instrument", "Channel", "Accessor", "Adapter", "Options", "Attributes",
    "Description",
)  # fmt: skip


def flow(value: Any) -> str:
    """Compact one-line YAML for a table cell ("2" stays quoted, DEV4 does not)."""
    if value is None or value == {} or value == "":
        return ""
    text = yaml.safe_dump(
        [value], default_flow_style=True, sort_keys=False, width=10**9
    )
    return text.strip()[1:-1]


def parse_cell(text: str, what: str) -> Any:
    text = text.strip()
    if not text:
        return None
    try:
        return yaml.load(text, Loader=ProfileLoader)
    except yaml.YAMLError as e:
        raise StationError(f"{what}: invalid YAML {text!r}: {e}") from e


class ProfileEditor(QDialog):
    """Edit tables or YAML; both views stay in sync; Save validates first."""

    def __init__(self, config: StationConfig, path: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Station profile — {config.name}")
        self.resize(1500, 700)
        self.path = path
        self.saved_config: Optional[StationConfig] = None
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.name = QLineEdit(config.name)
        self.description = QLineEdit(config.description)
        header.addWidget(QLabel("Name"))
        header.addWidget(self.name)
        header.addWidget(QLabel("Description"))
        header.addWidget(self.description, 2)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.instruments = self._table(INSTRUMENT_COLUMNS, INSTRUMENT_WIDTHS)
        self.roles = self._table(ROLE_COLUMNS, ROLE_WIDTHS)
        self.tabs.addTab(
            self._with_buttons(self.instruments, self.add_instrument), "Instruments"
        )
        self.tabs.addTab(self._with_buttons(self.roles, self.add_role), "Roles")
        self.yaml = QPlainTextEdit()
        self.yaml.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.tabs.addTab(self.yaml, "YAML")
        self._current_tab = 0
        self.tabs.currentChanged.connect(self.sync_tabs)
        layout.addWidget(self.tabs)

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        layout.addWidget(self.problems)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btnValidate = buttons.addButton("Validate", QDialogButtonBox.ActionRole)
        self.btnSaveAs = buttons.addButton("Save as…", QDialogButtonBox.ActionRole)
        self.btnValidate.clicked.connect(self.validate)
        self.btnSaveAs.clicked.connect(self.save_as)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.load(config)

    # Building blocks
    @staticmethod
    def _table(columns, widths) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)
        return table

    def _with_buttons(self, table: QTableWidget, add) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.addWidget(table)
        row = QHBoxLayout()
        add_button, remove_button = QPushButton("Add"), QPushButton("Remove")
        add_button.clicked.connect(lambda: add())
        remove_button.clicked.connect(
            lambda: table.removeRow(table.currentRow())
            if table.currentRow() >= 0
            else None
        )
        row.addWidget(add_button)
        row.addWidget(remove_button)
        row.addStretch()
        layout.addLayout(row)
        return box

    @staticmethod
    def _line(table, row, column, text="") -> QLineEdit:
        line = QLineEdit(text)
        line.setFrame(False)
        table.setCellWidget(row, column, line)
        return line

    def add_instrument(
        self, instrument_id: str = "", spec: Optional[Dict] = None
    ) -> None:
        spec = spec or {}
        table = self.instruments
        row = table.rowCount()
        table.insertRow(row)
        self._line(table, row, 0, instrument_id)
        driver = QComboBox()
        driver.setEditable(True)
        driver.addItems(sorted(info.key for info in default_registry().all()))
        driver.setCurrentText(spec.get("driver", ""))
        table.setCellWidget(row, 1, driver)
        self._line(table, row, 2, flow(spec.get("connection")))
        self._line(table, row, 3, flow(spec.get("options")))
        simulate = QCheckBox()
        simulate.setChecked(bool(spec.get("simulate")))
        table.setCellWidget(row, 4, simulate)
        self._line(table, row, 5, flow(spec.get("sim_options")))
        self._line(table, row, 6, spec.get("title", ""))

    def add_role(self, role: str = "", spec: Optional[Dict] = None) -> None:
        spec = spec or {}
        table = self.roles
        row = table.rowCount()
        table.insertRow(row)
        self._line(table, row, 0, role)
        instrument = QComboBox()
        instrument.setEditable(True)
        instrument.addItems(self._instrument_ids())
        instrument.setCurrentText(spec.get("instrument", ""))
        table.setCellWidget(row, 1, instrument)
        channel = spec.get("channel")
        self._line(table, row, 2, "" if channel is None else flow(channel))
        self._line(table, row, 3, spec.get("accessor", ""))
        adapter = QComboBox()
        adapter.addItems([""] + sorted(ADAPTERS))
        adapter.setCurrentText(spec.get("adapter") or "")
        table.setCellWidget(row, 4, adapter)
        self._line(table, row, 5, flow(spec.get("options")))
        self._line(table, row, 6, flow(spec.get("attributes")))
        self._line(table, row, 7, spec.get("description", ""))

    def _instrument_ids(self) -> List[str]:
        table = self.instruments
        return [
            table.cellWidget(row, 0).text().strip()
            for row in range(table.rowCount())
            if table.cellWidget(row, 0).text().strip()
        ]

    # Model <-> widgets
    def load(self, config: StationConfig) -> None:
        data = station_to_dict(config)
        self._load_dict(data)
        self.yaml.setPlainText(dump_station(config))

    def _load_dict(self, data: Dict) -> None:
        self.name.setText(data.get("name", ""))
        self.description.setText(data.get("description", ""))
        self.instruments.setRowCount(0)
        self.roles.setRowCount(0)
        # Metadata (e.g. SIS calibration) has no column: keep it as is
        self._metadata = {
            "instruments": {
                k: v.get("metadata") for k, v in (data.get("instruments") or {}).items()
            },
            "roles": {
                k: v.get("metadata") for k, v in (data.get("roles") or {}).items()
            },
        }
        for instrument_id, spec in (data.get("instruments") or {}).items():
            self.add_instrument(instrument_id, spec)
        for role, spec in (data.get("roles") or {}).items():
            self.add_role(role, spec)

    def tables_dict(self) -> Dict:
        instruments, roles = {}, {}
        table = self.instruments
        for row in range(table.rowCount()):
            instrument_id = table.cellWidget(row, 0).text().strip()
            where = f"instrument {instrument_id or row + 1}"
            spec = {
                "driver": table.cellWidget(row, 1).currentText().strip(),
                "connection": parse_cell(
                    table.cellWidget(row, 2).text(), f"{where} connection"
                ),
                "options": parse_cell(
                    table.cellWidget(row, 3).text(), f"{where} options"
                ),
                "simulate": table.cellWidget(row, 4).isChecked(),
                "sim_options": parse_cell(
                    table.cellWidget(row, 5).text(), f"{where} sim options"
                ),
                "title": table.cellWidget(row, 6).text().strip(),
                "metadata": self._metadata["instruments"].get(instrument_id),
            }
            instruments[instrument_id] = {
                k: v for k, v in spec.items() if v not in (None, "", False)
            }
        table = self.roles
        for row in range(table.rowCount()):
            role = table.cellWidget(row, 0).text().strip()
            where = f"role {role or row + 1}"
            spec = {
                "instrument": table.cellWidget(row, 1).currentText().strip(),
                "channel": parse_cell(
                    table.cellWidget(row, 2).text(), f"{where} channel"
                ),
                "accessor": table.cellWidget(row, 3).text().strip(),
                "adapter": table.cellWidget(row, 4).currentText().strip(),
                "options": parse_cell(
                    table.cellWidget(row, 5).text(), f"{where} options"
                ),
                "attributes": parse_cell(
                    table.cellWidget(row, 6).text(), f"{where} attributes"
                ),
                "description": table.cellWidget(row, 7).text().strip(),
                "metadata": self._metadata["roles"].get(role),
            }
            roles[role] = {k: v for k, v in spec.items() if v is not None and v != ""}
        return {
            "version": 1,
            "name": self.name.text().strip(),
            "description": self.description.text().strip(),
            "instruments": instruments,
            "roles": roles,
        }

    def yaml_dict(self) -> Dict:
        try:
            data = yaml.load(self.yaml.toPlainText(), Loader=ProfileLoader)
        except yaml.YAMLError as e:
            raise StationError(f"invalid YAML: {e}") from e
        if not isinstance(data, dict):
            raise StationError("Station profile must be a mapping")
        return data

    def config(self) -> StationConfig:
        """The edited profile, from the tab being edited; raises StationError."""
        data = (
            self.yaml_dict()
            if self.tabs.currentWidget() is self.yaml
            else self.tables_dict()
        )
        return station_from_dict(data)

    def sync_tabs(self, index: int) -> None:
        previous, self._current_tab = self._current_tab, index
        try:
            if index == 2 and previous != 2:
                config = station_from_dict(self.tables_dict())
                self.yaml.setPlainText(dump_station(config))
            elif index != 2 and previous == 2:
                self._load_dict(station_to_dict(station_from_dict(self.yaml_dict())))
            self.problems.clear()
        except StationError as e:
            self.problems.setText(str(e))

    # Actions
    def validate(self) -> Optional[StationConfig]:
        try:
            config = self.config()
        except StationError as e:
            self.problems.setText(str(e))
            return None
        registry = default_registry()
        unknown = [
            f"{instrument_id}: unknown driver {spec.driver!r}"
            for instrument_id, spec in config.instruments.items()
            if spec.driver not in registry
        ]
        if unknown:
            self.problems.setText("; ".join(unknown))
            return None
        self.problems.setText("Profile is valid")
        return config

    def save(self) -> None:
        if not self.path:
            self.save_as()
            return
        self._save_to(self.path)

    def save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save station profile",
            self.path or "stations",
            "Station profiles (*.yaml)",
        )
        if path:
            self.path = path
            self._save_to(path)

    def _save_to(self, path: str) -> None:
        config = self.validate()
        if config is None:
            QMessageBox.warning(self, "Station profile", self.problems.text())
            return
        save_station(config, path)
        self.saved_config = config
        self.accept()
