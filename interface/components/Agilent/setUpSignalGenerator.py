from api.Agilent.signal_generator import SignalGenerator
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import AgilentSignalGeneratorManager


class SetUpAgilentSignalGenerator(SetUpDeviceWidget):
    widget_title = "Agilent Signal Generator"
    manager_class = AgilentSignalGeneratorManager
    device_api_class = SignalGenerator
