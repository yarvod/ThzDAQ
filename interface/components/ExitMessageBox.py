from PyQt5.QtWidgets import QMessageBox, QCheckBox, QGridLayout


class ExitMessageBox(QMessageBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Exit")
        self.setText("Are you sure you want to exit?")
        self.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        self.setDefaultButton(QMessageBox.StandardButton.No)
        self.setIcon(QMessageBox.Icon.Question)
        self.dumpDataCheck = QCheckBox(self)
        self.dumpDataCheck.setChecked(True)
        self.dumpDataCheck.setText("Dump all data on exit")
        self.storeStateCheck = QCheckBox(self)
        self.storeStateCheck.setChecked(False)
        self.storeStateCheck.setText("Store app state")
        layout = self.layout()
        check_layout = QGridLayout()
        check_layout.addWidget(self.dumpDataCheck, 0, 0)
        check_layout.addWidget(self.storeStateCheck, 1, 0)
        layout.addItem(check_layout)
        self.setLayout(layout)
