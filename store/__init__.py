from store.deviceConfig import DeviceManager


class KeithleyPowerSupplyManager(DeviceManager):
    name = "Keithley Power Supply"
    main_widget_class = "interface.views.keithleyTabWidget.KeithleyTabWidget"


def restore_configs():
    KeithleyPowerSupplyManager.restore_config()
