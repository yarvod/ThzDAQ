from api import SpectrumBlock
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import RohdeSchwarzSpectrumFsek30Manager


class SetUpSpectrumFsek30Widget(SetUpDeviceWidget):
    widget_title = "Rohde Schwarz Spectrum FSEK 30"
    manager_class = RohdeSchwarzSpectrumFsek30Manager
    device_api_class = SpectrumBlock
