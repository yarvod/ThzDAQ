from PySide6.QtWidgets import (
    QGroupBox,
    QSizePolicy,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
)

from api.Rigol.DP832A import PowerSupplyDP832A
from store import RigolPowerSupplyManager
from interface.components.ui.Button import Button
from threads import Thread
from utils.exceptions import DeviceConnectionError


class SetOutputThread(Thread):
    def __init__(self, cid: int, channel_value_dict: dict):
        super().__init__()
        self.cid = cid
        self.channel_value_dict = channel_value_dict
        self.config = RigolPowerSupplyManager.get_config(self.cid)
        self.rigol = None

    def run(self):
        try:
            self.rigol = PowerSupplyDP832A(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return
        for channel, value in self.channel_value_dict.items():
            self.rigol.set_output(channel=channel, value=value)

        self.pre_exit()
        self.finished.emit()


class ManagerWidget(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.setTitle("Output")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cid = cid
        self.config = RigolPowerSupplyManager.get_config(cid=self.cid)
        self.set_output_thread = None
        layout = QVBoxLayout()
        hlayout = QHBoxLayout()

        self.ch1Label = QCheckBox(self)
        self.ch1Label.setChecked(self.config.output_ch1)
        self.ch1Label.setText("CH1")
        self.ch1Label.setStyleSheet("color: black; font-size: 18px; font-weight: bold;")
        self.ch1Label.setToolTip("Output CH1")

        self.ch2Label = QCheckBox(self)
        self.ch2Label.setChecked(self.config.output_ch2)
        self.ch2Label.setText("CH2")
        self.ch2Label.setStyleSheet("color: black; font-size: 18px; font-weight: bold;")
        self.ch2Label.setToolTip("Output CH2")

        self.ch3Label = QCheckBox(self)
        self.ch3Label.setChecked(self.config.output_ch3)
        self.ch3Label.setText("CH3")
        self.ch3Label.setStyleSheet("color: black; font-size: 18px; font-weight: bold;")
        self.ch3Label.setToolTip("Output CH3")

        self.btnSetOutput = Button(self, animate=True)
        self.btnSetOutput.setText("Set Output")
        self.btnSetOutput.clicked.connect(self.set_output)

        hlayout.addWidget(self.ch1Label)
        hlayout.addWidget(self.ch2Label)
        hlayout.addWidget(self.ch3Label)
        hlayout.addWidget(self.btnSetOutput)
        layout.addLayout(hlayout)
        self.setLayout(layout)

    def set_output(self):
        self.set_output_thread = SetOutputThread(
            cid=self.cid,
            channel_value_dict={
                1: self.ch1Label.isChecked(),
                2: self.ch2Label.isChecked(),
                3: self.ch3Label.isChecked(),
            },
        )

        self.set_output_thread.start()

        self.btnSetOutput.setEnabled(False)
        self.set_output_thread.finished.connect(
            lambda: self.btnSetOutput.setEnabled(True)
        )
