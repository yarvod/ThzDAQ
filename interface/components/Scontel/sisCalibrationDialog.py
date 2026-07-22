import json

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from store.sisCalibration import (
    default_sis_calibration,
    normalize_sis_calibration,
)


class SisCalibrationDialog(QDialog):
    def __init__(
        self,
        parent,
        block_name: str,
        bias_dev: str,
        calibration_coefficients: dict,
    ):
        super().__init__(parent)
        self.bias_dev = bias_dev
        self.calibration_coefficients = normalize_sis_calibration(
            calibration_coefficients
        )

        self.setWindowTitle(f"Calibration coefficients — {block_name} ({bias_dev})")
        self.setMinimumSize(680, 540)

        layout = QVBoxLayout(self)
        description = QLabel(
            "Edit the complete calibration JSON. All fields are required; vector "
            "fields must contain exactly two finite numbers.",
            self,
        )
        description.setWordWrap(True)

        self.editor = QPlainTextEdit(self)
        self.editor.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self._set_editor_value(self.calibration_coefficients)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults,
            parent=self,
        )
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).clicked.connect(self._restore_defaults)

        layout.addWidget(description)
        layout.addWidget(self.editor)
        layout.addWidget(self.buttons)

    def _set_editor_value(self, calibration_coefficients: dict):
        self.editor.setPlainText(
            json.dumps(calibration_coefficients, ensure_ascii=False, indent=4)
        )

    def _restore_defaults(self):
        self._set_editor_value(default_sis_calibration(self.bias_dev))

    def _save(self):
        try:
            value = json.loads(self.editor.toPlainText())
            self.calibration_coefficients = normalize_sis_calibration(value)
        except (json.JSONDecodeError, ValueError) as error:
            QMessageBox.warning(self, "Invalid calibration coefficients", str(error))
            return
        self.accept()
