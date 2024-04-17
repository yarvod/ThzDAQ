from api import VNABlock
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import RohdeSchwarzVnaZva67Manager


class SetUpVnaZva67Widget(SetUpDeviceWidget):
    widget_title = "Rohde Schwarz VNA ZVA 67"
    manager_class = RohdeSchwarzVnaZva67Manager
    device_api_class = VNABlock
