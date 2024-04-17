from api import TemperatureController
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import LakeShoreTemperatureControllerManager


class SetUpLakeshoreTemperatureControllerWidget(SetUpDeviceWidget):
    widget_title = "LakeShore Temperature Controller"
    manager_class = LakeShoreTemperatureControllerManager
    device_api_class = TemperatureController
