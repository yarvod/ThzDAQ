from typing import Literal

import settings
from utils.classes import BaseInstrument


HMP2030_CHANNEL_TYPES = Literal[1, 2, 3]


class PowerSupplyHMP2030(BaseInstrument):
    model = "HMP 2030"
    """
    Default port 5025
    Default host 169.254.0.30
    """

    def __init__(
        self,
        host: str = "169.254.0.30",
        gpib: int = None,
        adapter: str = settings.SOCKET,
        *args,
        **kwargs,
    ):
        super().__init__(host, gpib, adapter, *args, **kwargs)

    def idn(self):
        return self.query("*IDN?")

    def reset(self):
        self.write("*RST")

    def test(self) -> bool:
        """Test function: 0 - Good, 1 - Bad"""
        resp = self.query("*TST?").strip()
        return resp == "0"

    def set_channel(self, channel: HMP2030_CHANNEL_TYPES):
        """
        Channel 1|2|3
        """
        self.write(f"INSTrument:NSELest {channel}")

    def get_channel(self):
        return int(self.query("INSTrument:NSELect?"))

    def set_output_state(self, channel: HMP2030_CHANNEL_TYPES, value: bool):
        """
        Channel 1|2|3
        Output State 0 - off, 1 - on"""
        self.set_channel(channel)
        int_value = 1 if value else 0
        self.write(f"OUTPut:STATe {int_value}")

    def set_output_states(self, value: bool):
        for channel in range(1, 4):
            self.set_output_state(channel, value)

    def set_global_output_state(self, value: bool):
        int_value = 1 if value else 0
        self.write(f"OUTPut:GENeral {int_value}")

    def select_channels(self, value: bool):
        int_value = 1 if value else 0
        self.write(f"OUTPut:SELect {int_value}")

    def get_output_state(self, channel: HMP2030_CHANNEL_TYPES) -> bool:
        """
        Channel 1|2|3
        Output State 0 - off, 1 - on"""
        self.set_channel(channel)
        return self.query(f"OUTPut:STATe?") == "1"


if __name__ == "__main__":
    dev = PowerSupplyHMP2030(host="169.254.0.30", port=5025, delay=0.01)
    print(dev.idn())
    dev.set_output_state(1, False)
