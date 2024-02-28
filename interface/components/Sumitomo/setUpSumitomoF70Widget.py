from api import F70Rest
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import SumitomoF70Manager


class SetUpSumitomoF70Widget(SetUpDeviceWidget):
    title = "Sumitomo F70 Compressor"
    manager_class = SumitomoF70Manager
    device_api_class = F70Rest
