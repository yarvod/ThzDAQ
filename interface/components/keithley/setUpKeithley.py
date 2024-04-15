from api.Keithley import PowerSupply
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import KeithleyPowerSupplyManager


class SetUpKeithley(SetUpDeviceWidget):
    widget_title = "Keithley Power Supply"
    manager_class = KeithleyPowerSupplyManager
    device_api_class = PowerSupply
