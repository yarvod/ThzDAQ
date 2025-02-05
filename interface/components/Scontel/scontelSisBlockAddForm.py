from PyQt5.QtWidgets import QLabel, QComboBox

from interface.components.deviceAddForm import DeviceAddForm


class ScontelSisBlockAddForm(DeviceAddForm):
    def get_initialize_kwargs(self):
        kwargs = super().get_initialize_kwargs()
        new_kwargs = {
            "bias_dev": self.biasDev.currentText(),
            "ctrl_dev": self.ctrlDev.currentText(),
        }
        kwargs.update(new_kwargs)
        return kwargs

    def add_custom_form_fields(self, flayout, **kwargs):
        self.ctrlDevLabel = QLabel(self)
        self.ctrlDevLabel.setText("CTRL Device:")
        self.ctrlDev = QComboBox(self)
        self.ctrlDev.addItems(["DEV1", "DEV3"])
        self.ctrlDev.setCurrentText(kwargs.get("ctrl_dev", "DEV3"))

        self.biasDevLabel = QLabel(self)
        self.biasDevLabel.setText("BIAS Device:")
        self.biasDev = QComboBox(self)
        self.biasDev.addItems(["DEV2", "DEV4"])
        self.biasDev.setCurrentText(kwargs.get("bias_dev", "DEV4"))

        flayout.addRow(self.biasDevLabel, self.biasDev)
        flayout.addRow(self.ctrlDevLabel, self.ctrlDev)
