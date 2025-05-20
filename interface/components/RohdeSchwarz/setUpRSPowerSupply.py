from api import PowerSupplyHMP2030
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import RohdeSchwarzPowerSupplyManager


class SetUpRSPowerSupplyWidget(SetUpDeviceWidget):
    widget_title = "Rohde Schwarz Power Supply"
    manager_class = RohdeSchwarzPowerSupplyManager
    device_api_class = PowerSupplyHMP2030
