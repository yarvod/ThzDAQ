from api import GridDevice
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import GridManager


class SetUpGridWidget(SetUpDeviceWidget):
    widget_title = "Grid"
    manager_class = GridManager
    device_api_class = GridDevice
