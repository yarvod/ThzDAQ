from PyQt5.QtWidgets import QLabel

from interface.components.deviceInfo import DeviceInfo


class ScontelSisBlockInfoWidget(DeviceInfo):
    def get_initialize_kwargs(self):
        kwargs = super().get_initialize_kwargs()
        new_kwargs = {
            "bias_dev": self.biasDev.text(),
            "ctrl_dev": self.ctrlDev.text(),
        }
        kwargs.update(new_kwargs)
        return kwargs

    def add_custom_form_fields(self, flayout):
        self.ctrlDevLabel = QLabel(self)
        self.ctrlDevLabel.setText("CTRL Device:")
        self.ctrlDev = QLabel(self)
        self.ctrlDev.setText(self.form_kwargs.get("ctrl_dev"))

        self.biasDevLabel = QLabel(self)
        self.biasDevLabel.setText("BIAS Device:")
        self.biasDev = QLabel(self)
        self.biasDev.setText(self.form_kwargs.get("bias_dev"))

        flayout.addRow(self.biasDevLabel, self.biasDev)
        flayout.addRow(self.ctrlDevLabel, self.ctrlDev)
