import logging
import time
from typing import Callable, Dict, Optional

import numpy as np

from api.Agilent.signal_generator import SignalGenerator
from api.Chopper import chopper_manager
from api.NationalInstruments.yig_filter import NiYIGManager
from api.Rigol.DP832A import PowerSupplyDP832A
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.RohdeSchwarz.power_supply import PowerSupplyHMP2030
from api.RohdeSchwarz.spectrum_fsek30 import SpectrumBlock
from api.Scontel.sis_block import SisBlock
from interface.views.measures.two_sb.params import IF_SWITCH_RIGOL, TwoSbSetup
from store import (
    AgilentSignalGeneratorManager,
    RigolPowerSupplyManager,
    RohdeSchwarzPowerSupplyManager,
    RohdeSchwarzSpectrumFsek30Manager,
    ScontelSisBlockManager,
)
from store.state import state

logger = logging.getLogger(__name__)


class TwoSbSetupError(Exception):
    pass


class IfSwitch:
    """IF channel switch driven by a power supply output."""

    def __init__(
        self,
        supply,
        kind: str,
        channel: int,
        upper_when_on: bool = True,
        yig_power_channel: int = 0,
    ):
        self.supply = supply
        self.kind = kind
        self.channel = channel
        self.upper_when_on = upper_when_on
        self.yig_power_channel = yig_power_channel

    def _set_output(self, channel: int, value: bool):
        if self.kind == IF_SWITCH_RIGOL:
            self.supply.set_output(channel, value)
        else:
            self.supply.set_output_state(channel, value)

    def select(self, side_band: str):
        self._set_output(self.channel, (side_band == "upper") == self.upper_when_on)

    def set_yig_power(self, value: bool):
        if self.yig_power_channel:
            self._set_output(self.yig_power_channel, value)


class YigPowerDetector:
    """IF power through the YIG filter measured by the power meter."""

    def __init__(self, devices: "TwoSbDevices", point_delay: float):
        self.devices = devices
        self.point_delay = point_delay

    def prepare(self):
        self.devices.if_switch.set_yig_power(True)

    def measure(self, if_frequency: float, first: bool = False) -> float:
        self.devices.set_yig_frequency(if_frequency)
        time.sleep(self.point_delay)
        return self.devices.read_power()


class SpectrumPeakDetector:
    """Test tone peak power measured by the spectrum analyzer."""

    def __init__(
        self,
        devices: "TwoSbDevices",
        rbw: float,
        vbw: float,
        span: float,
        averages: int = 5,
        point_delay: float = 0.1,
        first_point_delay: float = 2,
    ):
        self.devices = devices
        self.rbw = rbw
        self.vbw = vbw
        self.span = span
        self.averages = max(1, int(averages))
        self.point_delay = point_delay
        self.first_point_delay = first_point_delay

    def prepare(self):
        self.devices.if_switch.set_yig_power(False)
        spectrum = self.devices.spectrum
        spectrum.set_single_sweep_mode()
        spectrum.set_video_bw(self.vbw)
        spectrum.set_resolution_bw(self.rbw)
        spectrum.set_span_frequency(self.span * 1e3)

    def measure(self, if_frequency: float, first: bool = False) -> float:
        spectrum = self.devices.spectrum
        spectrum.set_center_frequency(if_frequency)
        time.sleep(self.first_point_delay if first else self.point_delay)
        # FSEK answers with stale markers right after retuning, flush them
        for _ in range(3):
            spectrum.trigger()
        time.sleep(0.05)
        for _ in range(5):
            spectrum.get_peak_power()
        powers = []
        for _ in range(self.averages):
            spectrum.peak_search()
            powers.append(spectrum.get_peak_power())
            time.sleep(0.01)
        return float(np.mean(powers))


class TwoSbDevices:
    """Lazily opened instruments for 2SB measures, built from the app device configs."""

    def __init__(self, setup: TwoSbSetup):
        self.setup = setup
        self._instances: Dict[str, object] = {}

    def _get(self, key: str, factory: Callable[[], object]):
        if key not in self._instances:
            self._instances[key] = factory()
        return self._instances[key]

    @staticmethod
    def _config(manager, cid: Optional[int], label: str):
        config = manager.get_config(cid) if cid is not None else None
        if config is None:
            raise TwoSbSetupError(f"{label} is not selected")
        return config

    def _sis(self, cid: Optional[int], label: str) -> SisBlock:
        config = self._config(ScontelSisBlockManager, cid, label)
        return SisBlock(**config.dict())

    @property
    def sis1(self) -> SisBlock:
        return self._get("sis1", lambda: self._sis(self.setup.sis1_cid, "SIS 1"))

    @property
    def sis2(self) -> SisBlock:
        return self._get("sis2", lambda: self._sis(self.setup.sis2_cid, "SIS 2"))

    @property
    def lo(self) -> SignalGenerator:
        return self._get(
            "lo",
            lambda: SignalGenerator(
                **self._config(
                    AgilentSignalGeneratorManager, self.setup.lo_cid, "LO generator"
                ).dict()
            ),
        )

    @property
    def test_tone(self) -> SignalGenerator:
        return self._get(
            "test_tone",
            lambda: SignalGenerator(
                **self._config(
                    AgilentSignalGeneratorManager,
                    self.setup.test_tone_cid,
                    "Test tone generator",
                ).dict()
            ),
        )

    @property
    def nrx(self) -> NRXPowerMeter:
        return self._get(
            "nrx",
            lambda: NRXPowerMeter(
                host=state.NRX_IP, aperture_time=state.NRX_APER_TIME, delay=0
            ),
        )

    @property
    def yig(self) -> NiYIGManager:
        return self._get("yig", NiYIGManager)

    @property
    def spectrum(self) -> SpectrumBlock:
        def factory():
            config = self._config(
                RohdeSchwarzSpectrumFsek30Manager,
                self.setup.spectrum_cid,
                "Spectrum analyzer",
            )
            return SpectrumBlock(**config.dict(), delay=config.delay)

        return self._get("spectrum", factory)

    @property
    def if_switch(self) -> IfSwitch:
        def factory():
            if self.setup.if_switch_kind == IF_SWITCH_RIGOL:
                manager, supply_class = RigolPowerSupplyManager, PowerSupplyDP832A
            else:
                manager, supply_class = (
                    RohdeSchwarzPowerSupplyManager,
                    PowerSupplyHMP2030,
                )
            config = self._config(
                manager, self.setup.if_switch_cid, "IF switch power supply"
            )
            return IfSwitch(
                supply=supply_class(**config.dict()),
                kind=self.setup.if_switch_kind,
                channel=self.setup.if_switch_channel,
                upper_when_on=self.setup.upper_when_on,
                yig_power_channel=self.setup.yig_power_channel,
            )

        return self._get("if_switch", factory)

    @property
    def chopper(self):
        return chopper_manager.chopper

    def set_lo_frequency(self, frequency: float):
        """Frequency at the mixer, Hz"""
        self.lo.set_frequency(frequency / self.setup.lo_multiplier)

    def set_test_tone_frequency(self, frequency: float):
        """Frequency at the mixer, Hz"""
        self.test_tone.set_frequency(frequency / self.setup.test_tone_multiplier)

    def set_yig_frequency(self, frequency: float):
        response = self.yig.set_frequency(frequency, yig=self.setup.yig)
        if response is not None:
            state.DIGITAL_YIG_MAP[self.setup.yig].value = response

    def read_power(self, attempts: int = 3) -> float:
        for _ in range(attempts):
            power = self.nrx.get_power()
            if power is not None:
                return power
        raise RuntimeError("Unable to read power meter")

    def close(self):
        # Prologix and single-socket adapters are shared app-wide, keep them open
        for key in ("sis1", "sis2"):
            block = self._instances.get(key)
            if block is not None:
                block.disconnect()
        nrx = self._instances.get("nrx")
        if nrx is not None and nrx.adapter is not None:
            nrx.adapter.close()
        self._instances.clear()
