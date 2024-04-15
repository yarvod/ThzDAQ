from api.Rigol.DP832A import PowerSupplyDP832A
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import RigolPowerSupplyManager


class SetUpRigolPowerSupplyWidget(SetUpDeviceWidget):
    widget_title = "Rigol Power Supply"
    manager_class = RigolPowerSupplyManager
    device_api_class = PowerSupplyDP832A
