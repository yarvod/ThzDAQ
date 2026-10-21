import logging
from typing import Dict, List, Optional, Tuple, Type

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from interface.components.deviceComboBox import DeviceComboBox
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.ui.Lines import HLine
from interface.components.ui.SpinBox import SpinBox
from interface.views.measures.two_sb.params import (
    DETECTOR_SPECTRUM,
    DETECTORS,
    IF_SWITCH_KINDS,
    IF_SWITCH_RIGOL,
    SOURCE_LO,
    SOURCE_RF,
    HotColdParams,
    IfBalanceParams,
    IfSweep,
    OptimizationParams,
    PumpBalanceParams,
    SrrParams,
    TnParams,
    TwoSbSetup,
)
from interface.views.measures.two_sb.threads import (
    IfBalanceThread,
    OptimizationThread,
    PumpBalanceThread,
    SrrThread,
    TnThread,
    TwoSbThread,
)
from store import (
    AgilentSignalGeneratorManager,
    RigolPowerSupplyManager,
    RohdeSchwarzPowerSupplyManager,
    RohdeSchwarzSpectrumFsek30Manager,
    ScontelSisBlockManager,
)
from utils.dock import Dock
from utils.two_sb import SIDE_BANDS, parse_float_list

logger = logging.getLogger(__name__)

MAPS_DOCK = "2SB Tn-SRR maps"

SETUP_LABELS = {
    "sis1_cid": "SIS 1",
    "sis2_cid": "SIS 2",
    "lo_cid": "LO generator",
    "test_tone_cid": "Test tone generator",
    "if_switch_cid": "IF switch power supply",
    "spectrum_cid": "Spectrum analyzer",
}


def double_spin(parent, minimum, maximum, value, decimals=2) -> DoubleSpinBox:
    spin = DoubleSpinBox(parent)
    spin.setDecimals(decimals)
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


def int_spin(parent, minimum, maximum, value) -> SpinBox:
    spin = SpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


class TwoSbDevicesGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__("2SB devices", parent)
        layout = QFormLayout(self)
        default = TwoSbSetup()

        self.sis1Config = DeviceComboBox(self, ScontelSisBlockManager)
        self.sis2Config = DeviceComboBox(self, ScontelSisBlockManager)

        self.loConfig = DeviceComboBox(self, AgilentSignalGeneratorManager)
        self.loMultiplier = double_spin(self, 1, 1000, default.lo_multiplier)
        self.testToneConfig = DeviceComboBox(self, AgilentSignalGeneratorManager)
        self.testToneMultiplier = double_spin(
            self, 1, 1000, default.test_tone_multiplier
        )
        self.prefer_other_config(self.sis2Config, self.sis1Config)
        self.prefer_other_config(self.testToneConfig, self.loConfig)

        self.ifSwitchKind = QComboBox(self)
        self.ifSwitchKind.addItems(IF_SWITCH_KINDS)
        self.rigolConfig = DeviceComboBox(self, RigolPowerSupplyManager)
        self.rsConfig = DeviceComboBox(self, RohdeSchwarzPowerSupplyManager)
        self.ifSwitchChannel = int_spin(self, 1, 3, default.if_switch_channel)
        self.upperWhenOn = QCheckBox("Upper IF channel when output is ON", self)
        self.upperWhenOn.setChecked(default.upper_when_on)
        self.yigPowerChannel = int_spin(self, 0, 3, default.yig_power_channel)
        self.yigPowerChannel.setToolTip(
            "Power supply channel feeding the YIG filter, 0 - not controlled"
        )
        self.yigType = QComboBox(self)
        self.yigType.addItems(["yig_1", "yig_2"])
        self.spectrumConfig = DeviceComboBox(self, RohdeSchwarzSpectrumFsek30Manager)

        self.ifSwitchSupplyLabel = QLabel("IF switch supply", self)
        self.ifSwitchKind.currentTextChanged.connect(self.toggle_if_switch_kind)

        layout.addRow("SIS 1", self.sis1Config)
        layout.addRow("SIS 2", self.sis2Config)
        layout.addRow(HLine(self))
        layout.addRow("LO generator", self.loConfig)
        layout.addRow("LO multiplier", self.loMultiplier)
        layout.addRow("Test tone generator", self.testToneConfig)
        layout.addRow("Test tone multiplier", self.testToneMultiplier)
        layout.addRow(HLine(self))
        layout.addRow("IF switch type", self.ifSwitchKind)
        layout.addRow(self.ifSwitchSupplyLabel, self.rigolConfig)
        layout.addRow(self.rsConfig)
        layout.addRow("IF switch channel", self.ifSwitchChannel)
        layout.addRow(self.upperWhenOn)
        layout.addRow("YIG supply channel", self.yigPowerChannel)
        layout.addRow("YIG", self.yigType)
        layout.addRow("Spectrum analyzer", self.spectrumConfig)
        self.toggle_if_switch_kind(self.ifSwitchKind.currentText())

    @staticmethod
    def prefer_other_config(combobox: DeviceComboBox, other: DeviceComboBox):
        """Point combobox to another device than `other` until the user picks one."""
        touched = []
        combobox.activated.connect(lambda _: touched.append(True))

        def update():
            if touched or combobox.count() < 2:
                return
            if combobox.currentIndex() == other.currentIndex():
                combobox.setCurrentIndex(1 if other.currentIndex() == 0 else 0)

        combobox.manager.event_manager.configs_updated.connect(update)
        update()

    def toggle_if_switch_kind(self, kind: str):
        rigol = kind == IF_SWITCH_RIGOL
        self.rigolConfig.setVisible(rigol)
        self.rsConfig.setVisible(not rigol)

    def setup(self) -> TwoSbSetup:
        kind = self.ifSwitchKind.currentText()
        if_switch = self.rigolConfig if kind == IF_SWITCH_RIGOL else self.rsConfig
        return TwoSbSetup(
            sis1_cid=self.sis1Config.current_cid(),
            sis2_cid=self.sis2Config.current_cid(),
            lo_cid=self.loConfig.current_cid(),
            lo_multiplier=self.loMultiplier.value(),
            test_tone_cid=self.testToneConfig.current_cid(),
            test_tone_multiplier=self.testToneMultiplier.value(),
            if_switch_kind=kind,
            if_switch_cid=if_switch.current_cid(),
            if_switch_channel=self.ifSwitchChannel.value(),
            upper_when_on=self.upperWhenOn.isChecked(),
            yig_power_channel=self.yigPowerChannel.value(),
            yig=self.yigType.currentText(),
            spectrum_cid=self.spectrumConfig.current_cid(),
        )


class IfSweepFields:
    def __init__(self, parent, layout: QFormLayout, default: IfSweep):
        self.start = double_spin(parent, 0, 40, default.start, 3)
        self.stop = double_spin(parent, 0, 40, default.stop, 3)
        self.points = int_spin(parent, 1, 10001, default.points)
        layout.addRow("IF start, GHz", self.start)
        layout.addRow("IF stop, GHz", self.stop)
        layout.addRow("IF points", self.points)

    def value(self) -> IfSweep:
        return IfSweep(
            start=self.start.value(),
            stop=self.stop.value(),
            points=self.points.value(),
        )


class HotColdFields:
    def __init__(self, parent, layout: QFormLayout, default: HotColdParams):
        self.t_hot = double_spin(parent, 0, 1000, default.t_hot)
        self.t_cold = double_spin(parent, 0, 1000, default.t_cold)
        self.chopper_delay = double_spin(parent, 0, 60, default.chopper_delay)
        layout.addRow("T hot, K", self.t_hot)
        layout.addRow("T cold, K", self.t_cold)
        layout.addRow("Chopper delay, s", self.chopper_delay)

    def value(self) -> HotColdParams:
        return HotColdParams(
            t_hot=self.t_hot.value(),
            t_cold=self.t_cold.value(),
            chopper_delay=self.chopper_delay.value(),
        )


class LoFields:
    def __init__(self, parent, layout: QFormLayout, frequency: float, enabled: bool):
        self.frequency = double_spin(parent, 0, 2000, frequency, 3)
        self.enabled = QCheckBox("Set LO frequency and output", parent)
        self.enabled.setChecked(enabled)
        layout.addRow("LO frequency, GHz", self.frequency)
        layout.addRow(self.enabled)


class SideBandFields:
    def __init__(self, parent, layout: QFormLayout):
        row = QHBoxLayout()
        self.checks = {}
        for side_band in SIDE_BANDS:
            check = QCheckBox(side_band.capitalize(), parent)
            check.setChecked(True)
            row.addWidget(check)
            self.checks[side_band] = check
        layout.addRow("Sidebands", row)

    def value(self) -> Tuple[str, ...]:
        side_bands = tuple(sb for sb, check in self.checks.items() if check.isChecked())
        if not side_bands:
            raise ValueError("Select at least one sideband")
        return side_bands


class TwoSbMeasureTab(QWidget):
    thread_class: Type[TwoSbThread] = None

    def __init__(self, parent, owner: "TwoSbMeasureWidget"):
        super().__init__(parent)
        self.owner = owner
        layout = QVBoxLayout(self)
        self.form = QFormLayout()
        self.build_form(self.form)
        layout.addLayout(self.form)

        self.progress = QProgressBar(self)
        self.progress.setValue(0)
        self.btnStart = Button("Start", animate=True)
        self.btnStart.clicked.connect(lambda: self.owner.start_measure(self))
        self.btnStop = Button("Stop")
        self.btnStop.clicked.connect(self.owner.stop_measure)
        self.btnStop.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self.btnStart)
        buttons.addWidget(self.btnStop)
        layout.addWidget(self.progress)
        layout.addLayout(buttons)
        layout.addStretch()

    def build_form(self, form: QFormLayout):
        raise NotImplementedError

    def params(self):
        raise NotImplementedError

    def required_devices(self, params) -> List[str]:
        return ["sis1_cid", "sis2_cid", "if_switch_cid"]

    def bias_fields(self, form: QFormLayout, v1: float, v2: float, precise: bool):
        self.sis1Voltage = double_spin(self, -30, 30, v1, 3)
        self.sis2Voltage = double_spin(self, -30, 30, v2, 3)
        self.preciseBias = QCheckBox("Precise (iterative) bias setting", self)
        self.preciseBias.setChecked(precise)
        form.addRow("SIS 1 voltage, mV", self.sis1Voltage)
        form.addRow("SIS 2 voltage, mV", self.sis2Voltage)
        form.addRow(self.preciseBias)


class IfBalanceTab(TwoSbMeasureTab):
    thread_class = IfBalanceThread

    def build_form(self, form):
        default = IfBalanceParams()
        self.sis1Voltages = QLineEdit(", ".join(map(str, default.sis1_voltages)), self)
        self.sis2Voltages = QLineEdit(", ".join(map(str, default.sis2_voltages)), self)
        self.sis1Voltages.setToolTip(
            "Comma separated, all SIS1 x SIS2 pairs are measured"
        )
        self.sis2Voltages.setToolTip(
            "Comma separated, all SIS1 x SIS2 pairs are measured"
        )
        self.preciseBias = QCheckBox("Precise (iterative) bias setting", self)
        self.preciseBias.setChecked(default.precise_bias)
        form.addRow("SIS 1 voltages, mV", self.sis1Voltages)
        form.addRow("SIS 2 voltages, mV", self.sis2Voltages)
        form.addRow(self.preciseBias)
        self.ifSweep = IfSweepFields(self, form, default.if_sweep)
        self.switchDelay = double_spin(self, 0, 60, default.switch_delay)
        self.pointDelay = double_spin(self, 0, 10, default.point_delay, 3)
        form.addRow("IF switch delay, s", self.switchDelay)
        form.addRow("Point delay, s", self.pointDelay)

    def params(self) -> IfBalanceParams:
        sis1 = parse_float_list(self.sis1Voltages.text())
        sis2 = parse_float_list(self.sis2Voltages.text())
        if not sis1 or not sis2:
            raise ValueError("Enter SIS 1 and SIS 2 voltages")
        return IfBalanceParams(
            sis1_voltages=sis1,
            sis2_voltages=sis2,
            if_sweep=self.ifSweep.value(),
            precise_bias=self.preciseBias.isChecked(),
            switch_delay=self.switchDelay.value(),
            point_delay=self.pointDelay.value(),
        )


class PumpBalanceTab(TwoSbMeasureTab):
    thread_class = PumpBalanceThread

    def build_form(self, form):
        default = PumpBalanceParams()
        self.source = QComboBox(self)
        self.source.addItems([SOURCE_LO, SOURCE_RF])
        self.source.setToolTip(
            "LO - sweep LO generator, test tone off; RF - sweep test tone, LO off"
        )
        self.frequencyStart = double_spin(self, 0, 2000, default.frequency_start, 3)
        self.frequencyStop = double_spin(self, 0, 2000, default.frequency_stop, 3)
        self.frequencyPoints = int_spin(self, 1, 10001, default.frequency_points)
        self.sourcePower = double_spin(self, -130, 25, default.source_power)
        self.sis1Start = double_spin(self, -30, 30, default.sis1_voltage_start, 3)
        self.sis1Stop = double_spin(self, -30, 30, default.sis1_voltage_stop, 3)
        self.sis2Start = double_spin(self, -30, 30, default.sis2_voltage_start, 3)
        self.sis2Stop = double_spin(self, -30, 30, default.sis2_voltage_stop, 3)
        self.biasPoints = int_spin(self, 1, 1001, default.bias_points)
        self.biasDelay = double_spin(self, 0, 10, default.bias_delay, 3)
        self.measurePower = QCheckBox("Measure IF power", self)
        self.measurePower.setChecked(default.measure_power)
        form.addRow("Source", self.source)
        form.addRow("Frequency start, GHz", self.frequencyStart)
        form.addRow("Frequency stop, GHz", self.frequencyStop)
        form.addRow("Frequency points", self.frequencyPoints)
        form.addRow("Source power, dBm", self.sourcePower)
        form.addRow("SIS 1 voltage start, mV", self.sis1Start)
        form.addRow("SIS 1 voltage stop, mV", self.sis1Stop)
        form.addRow("SIS 2 voltage start, mV", self.sis2Start)
        form.addRow("SIS 2 voltage stop, mV", self.sis2Stop)
        form.addRow("Bias points", self.biasPoints)
        form.addRow("Bias delay, s", self.biasDelay)
        form.addRow(self.measurePower)

    def params(self) -> PumpBalanceParams:
        return PumpBalanceParams(
            source=self.source.currentText(),
            frequency_start=self.frequencyStart.value(),
            frequency_stop=self.frequencyStop.value(),
            frequency_points=self.frequencyPoints.value(),
            source_power=self.sourcePower.value(),
            sis1_voltage_start=self.sis1Start.value(),
            sis1_voltage_stop=self.sis1Stop.value(),
            sis2_voltage_start=self.sis2Start.value(),
            sis2_voltage_stop=self.sis2Stop.value(),
            bias_points=self.biasPoints.value(),
            bias_delay=self.biasDelay.value(),
            measure_power=self.measurePower.isChecked(),
        )

    def required_devices(self, params: PumpBalanceParams):
        source = "lo_cid" if params.source == SOURCE_LO else "test_tone_cid"
        return ["sis1_cid", "sis2_cid", source]


class SrrTab(TwoSbMeasureTab):
    thread_class = SrrThread

    def build_form(self, form):
        default = SrrParams()
        self.lo = LoFields(self, form, default.lo_frequency, default.set_lo)
        self.bias_fields(
            form, default.sis1_voltage, default.sis2_voltage, default.precise_bias
        )
        self.ifSweep = IfSweepFields(self, form, default.if_sweep)
        self.chunkSize = int_spin(self, 1, 10001, default.chunk_size)
        self.chunkSize.setToolTip("IF points measured per IF channel switch")
        form.addRow("Points per IF switch", self.chunkSize)
        self.sideBands = SideBandFields(self, form)

        self.detector = QComboBox(self)
        self.detector.addItems(DETECTORS)
        form.addRow("Detector", self.detector)
        self.spectrumGroup = QGroupBox("Spectrum analyzer", self)
        spectrum_form = QFormLayout(self.spectrumGroup)
        self.spectrumRbw = double_spin(self, 0, 10000, default.spectrum_rbw, 3)
        self.spectrumVbw = double_spin(self, 0, 10000, default.spectrum_vbw, 3)
        self.spectrumSpan = double_spin(self, 0, 1e6, default.spectrum_span, 3)
        self.spectrumAverages = int_spin(self, 1, 100, default.spectrum_averages)
        spectrum_form.addRow("RBW, kHz", self.spectrumRbw)
        spectrum_form.addRow("VBW, kHz", self.spectrumVbw)
        spectrum_form.addRow("Span, kHz", self.spectrumSpan)
        spectrum_form.addRow("Averages", self.spectrumAverages)
        form.addRow(self.spectrumGroup)
        self.detector.currentTextChanged.connect(
            lambda text: self.spectrumGroup.setVisible(text == DETECTOR_SPECTRUM)
        )
        self.spectrumGroup.setVisible(False)

        self.switchDelay = double_spin(self, 0, 60, default.switch_delay)
        self.pointDelay = double_spin(self, 0, 10, default.point_delay, 3)
        form.addRow("IF switch delay, s", self.switchDelay)
        form.addRow("Point delay, s", self.pointDelay)
        self.measureYFactor = QCheckBox("Measure Y-factor after SRR", self)
        self.measureYFactor.setChecked(default.measure_y_factor)
        form.addRow(self.measureYFactor)
        self.hotCold = HotColdFields(self, form, default.hot_cold)

    def params(self) -> SrrParams:
        return SrrParams(
            lo_frequency=self.lo.frequency.value(),
            set_lo=self.lo.enabled.isChecked(),
            sis1_voltage=self.sis1Voltage.value(),
            sis2_voltage=self.sis2Voltage.value(),
            precise_bias=self.preciseBias.isChecked(),
            if_sweep=self.ifSweep.value(),
            chunk_size=self.chunkSize.value(),
            side_bands=self.sideBands.value(),
            detector=self.detector.currentText(),
            spectrum_rbw=self.spectrumRbw.value(),
            spectrum_vbw=self.spectrumVbw.value(),
            spectrum_span=self.spectrumSpan.value(),
            spectrum_averages=self.spectrumAverages.value(),
            switch_delay=self.switchDelay.value(),
            point_delay=self.pointDelay.value(),
            measure_y_factor=self.measureYFactor.isChecked(),
            hot_cold=self.hotCold.value(),
        )

    def required_devices(self, params: SrrParams):
        required = ["sis1_cid", "sis2_cid", "if_switch_cid", "test_tone_cid"]
        if params.set_lo:
            required.append("lo_cid")
        if params.detector == DETECTOR_SPECTRUM:
            required.append("spectrum_cid")
        return required


class TnTab(TwoSbMeasureTab):
    thread_class = TnThread

    def build_form(self, form):
        default = TnParams()
        self.lo = LoFields(self, form, default.lo_frequency, default.set_lo)
        self.bias_fields(
            form, default.sis1_voltage, default.sis2_voltage, default.precise_bias
        )
        self.ifSweep = IfSweepFields(self, form, default.if_sweep)
        self.sideBands = SideBandFields(self, form)
        self.switchDelay = double_spin(self, 0, 60, default.switch_delay)
        self.pointDelay = double_spin(self, 0, 10, default.point_delay, 3)
        form.addRow("IF switch delay, s", self.switchDelay)
        form.addRow("Point delay, s", self.pointDelay)
        self.hotCold = HotColdFields(self, form, default.hot_cold)

    def params(self) -> TnParams:
        return TnParams(
            lo_frequency=self.lo.frequency.value(),
            set_lo=self.lo.enabled.isChecked(),
            sis1_voltage=self.sis1Voltage.value(),
            sis2_voltage=self.sis2Voltage.value(),
            precise_bias=self.preciseBias.isChecked(),
            if_sweep=self.ifSweep.value(),
            side_bands=self.sideBands.value(),
            switch_delay=self.switchDelay.value(),
            point_delay=self.pointDelay.value(),
            hot_cold=self.hotCold.value(),
        )

    def required_devices(self, params: TnParams):
        required = ["sis1_cid", "sis2_cid", "if_switch_cid"]
        if params.set_lo:
            required.append("lo_cid")
        return required


class OptimizationTab(TwoSbMeasureTab):
    thread_class = OptimizationThread

    def build_form(self, form):
        default = OptimizationParams()
        self.lo = LoFields(self, form, default.lo_frequency, default.set_lo)
        self.ifFrequency = double_spin(self, 0, 40, default.if_frequency, 3)
        form.addRow("IF frequency, GHz", self.ifFrequency)
        self.sis1Start = double_spin(self, -30, 30, default.sis1_voltage_start, 3)
        self.sis1Stop = double_spin(self, -30, 30, default.sis1_voltage_stop, 3)
        self.sis1Step = double_spin(self, 0.001, 30, default.sis1_voltage_step, 3)
        self.sis2Start = double_spin(self, -30, 30, default.sis2_voltage_start, 3)
        self.sis2Stop = double_spin(self, -30, 30, default.sis2_voltage_stop, 3)
        self.sis2Step = double_spin(self, 0.001, 30, default.sis2_voltage_step, 3)
        self.preciseBias = QCheckBox("Precise (iterative) bias setting", self)
        self.preciseBias.setChecked(default.precise_bias)
        form.addRow("SIS 1 voltage start, mV", self.sis1Start)
        form.addRow("SIS 1 voltage stop, mV", self.sis1Stop)
        form.addRow("SIS 1 voltage step, mV", self.sis1Step)
        form.addRow("SIS 2 voltage start, mV", self.sis2Start)
        form.addRow("SIS 2 voltage stop, mV", self.sis2Stop)
        form.addRow("SIS 2 voltage step, mV", self.sis2Step)
        form.addRow(self.preciseBias)
        self.toneDelay = double_spin(self, 0, 60, default.tone_delay)
        self.switchDelay = double_spin(self, 0, 60, default.switch_delay)
        form.addRow("Test tone delay, s", self.toneDelay)
        form.addRow("IF switch delay, s", self.switchDelay)
        self.hotCold = HotColdFields(self, form, default.hot_cold)

    def params(self) -> OptimizationParams:
        params = OptimizationParams(
            lo_frequency=self.lo.frequency.value(),
            set_lo=self.lo.enabled.isChecked(),
            if_frequency=self.ifFrequency.value(),
            sis1_voltage_start=self.sis1Start.value(),
            sis1_voltage_stop=self.sis1Stop.value(),
            sis1_voltage_step=self.sis1Step.value(),
            sis2_voltage_start=self.sis2Start.value(),
            sis2_voltage_stop=self.sis2Stop.value(),
            sis2_voltage_step=self.sis2Step.value(),
            precise_bias=self.preciseBias.isChecked(),
            tone_delay=self.toneDelay.value(),
            switch_delay=self.switchDelay.value(),
            hot_cold=self.hotCold.value(),
        )
        # Validate ranges before the thread is created
        params.sis1_voltages()
        params.sis2_voltages()
        return params

    def required_devices(self, params: OptimizationParams):
        required = ["sis1_cid", "sis2_cid", "if_switch_cid", "test_tone_cid"]
        if params.set_lo:
            required.append("lo_cid")
        return required


class CurvePlotter:
    """Streams thread curves into dock graph windows keeping one curve per label."""

    def __init__(self):
        self._plot_numbers: Dict[Tuple[str, int, str], int] = {}

    def plot(self, dock_name: str, payload: Dict):
        if Dock.ex is None:
            return
        dock = Dock.ex.dock_manager.findDockWidget(dock_name)
        if dock is None:
            return
        window = dock.widget()
        key = (dock_name, payload["measure_id"], payload["curve"])
        plot_num = self._plot_numbers.get(key)
        if plot_num is None:
            plot_num = window.get_last_plot_number() + 1
            self._plot_numbers[key] = plot_num
        window.plot(
            x=payload["x"],
            y=payload["y"],
            plot_num=plot_num,
            measure_id=payload["measure_id"],
            legend_postfix=payload["curve"],
        )
        window.show()


class TwoSbMeasureWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.thread: Optional[TwoSbThread] = None
        self.active_tab: Optional[TwoSbMeasureTab] = None
        self.plotter = CurvePlotter()

        self.tabs = QTabWidget(self)
        self.devicesGroup = TwoSbDevicesGroup(self.tabs)
        self.tabs.addTab(self.scrollable(self.devicesGroup), "Devices")
        self.measureTabs: List[TwoSbMeasureTab] = []
        for title, tab_class in (
            ("IF balance", IfBalanceTab),
            ("LO/RF balance", PumpBalanceTab),
            ("SRR", SrrTab),
            ("Tn", TnTab),
            ("Optimization", OptimizationTab),
        ):
            tab = tab_class(self.tabs, self)
            self.tabs.addTab(self.scrollable(tab), title)
            self.measureTabs.append(tab)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

    @staticmethod
    def scrollable(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    def start_measure(self, tab: TwoSbMeasureTab):
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.warning(self, "2SB measure", "Another 2SB measure is running")
            return
        try:
            params = tab.params()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid parameters", str(e))
            return
        setup = self.devicesGroup.setup()
        missing = [
            SETUP_LABELS[name]
            for name in tab.required_devices(params)
            if getattr(setup, name) is None
        ]
        if missing:
            QMessageBox.warning(
                self, "Device is not selected", f"Select: {', '.join(missing)}"
            )
            return

        self.thread = tab.thread_class(setup=setup, params=params)
        self.active_tab = tab
        self.thread.progress.connect(tab.progress.setValue)
        self.thread.plot.connect(self.plotter.plot)
        self.thread.error.connect(
            lambda message: QMessageBox.critical(self, "2SB measure error", message)
        )
        if isinstance(self.thread, OptimizationThread):
            self.thread.maps.connect(self.show_maps)
        self.thread.finished.connect(self.on_finished)
        self.set_running(True)
        self.thread.start()

    def stop_measure(self):
        if self.thread is not None:
            self.thread.request_stop()

    def on_finished(self):
        self.set_running(False)
        if self.active_tab is not None:
            self.active_tab.progress.setValue(0)
        self.active_tab = None

    def set_running(self, running: bool):
        # Other tabs keep Start enabled (animated buttons spin while disabled),
        # start_measure refuses to run two measures at once
        if self.active_tab is not None:
            self.active_tab.btnStart.setEnabled(not running)
            self.active_tab.btnStop.setEnabled(running)
        self.devicesGroup.setEnabled(not running)

    def show_maps(self, data: Dict):
        if Dock.ex is None:
            return
        dock = Dock.ex.dock_manager.findDockWidget(MAPS_DOCK)
        if dock is None:
            return
        dock.widget().update_maps(data)
        dock.widget().show()
