from api import SisBlock
from interface.components.Scontel.scontelSisBlockAddForm import ScontelSisBlockAddForm
from interface.components.Scontel.scontelSisBlockInfoWidget import (
    ScontelSisBlockInfoWidget,
)
from interface.components.setUpDeviceWidget import SetUpDeviceWidget
from store import ScontelSisBlockManager


class SetUpScontelSisBlockWidget(SetUpDeviceWidget):
    widget_title = "Scontel SIS Block"
    manager_class = ScontelSisBlockManager
    device_api_class = SisBlock
    device_add_form_class = ScontelSisBlockAddForm
    device_info_class = ScontelSisBlockInfoWidget
