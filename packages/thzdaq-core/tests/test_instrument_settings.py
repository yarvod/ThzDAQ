"""The configuration of an instrument comes one way: the persistent settings of
its profile, written as it opens to an instrument that does not keep them."""

import time

import pytest
from thzdaq_core.domain.station.profile import station_from_dict, station_to_dict
from thzdaq_core.domain.station.station import Station
from thzdaq_instruments.errors import InstrumentError
from thzdaq_instruments.transport import TransportPool
from thzdaq_instruments.transport.fake import FakeLink

NRX = {
    "driver": "rs.nrx",
    "connection": {"kind": "socket", "host": "169.254.2.20", "port": 5025},
}
GENERATOR = {
    "driver": "agilent.e8247c",
    "connection": {"kind": "prologix", "host": "10.0.0.3", "gpib": 19},
}


def profile(**instruments):
    return {"version": 2, "name": "bench", "instruments": instruments}


def opened(data, instrument_id):
    """The instrument opened from the profile over a fake link, and the link."""
    links = []
    pool = TransportPool(lambda spec: links.append(FakeLink()) or links[-1])
    station = Station(station_from_dict(data), pause=time.sleep, pool=pool)
    station.instrument(instrument_id)
    return station, links[0], pool


class TestOpen:
    def test_the_setting_a_person_made_is_what_the_meter_gets(self):
        """An NRX used to get its options (aperture 0.05 s) from its constructor
        on every open, while a person's change in its dock (0.2 s) was kept in
        the profile's settings and never written back: after a reopen the
        meter and its profile disagreed."""
        meter = {
            **NRX,
            "options": {"aperture_time": 0.05, "averaging": False},
            "settings": {"aperture_time": 0.2},
        }
        station, link, _ = opened(profile(power_meter_1=meter), "power_meter_1")
        assert "CALC:APER 0.2" in link.written
        assert "CALC:APER 0.05" not in link.written
        assert "CALC:CHAN:AVER:STAT 0" in link.written
        station.close()

    def test_an_instrument_that_keeps_its_configuration_is_not_touched(self):
        generator = {**GENERATOR, "settings": {"frequency_multiplier": 2.0}}
        station, link, _ = opened(
            profile(signal_generator_1=generator), "signal_generator_1"
        )
        assert link.written == []
        station.close()

    def test_settings_are_written_in_the_order_of_the_quantities(self):
        meter = {
            **NRX,
            "settings": {"limit_upper": 10.0, "aperture_time": 0.1, "power_unit": "W"},
        }
        station, link, _ = opened(profile(power_meter_1=meter), "power_meter_1")
        assert link.written == [
            "UNIT1:POW W",
            "CALC:APER 0.1",
            "CALC1:LIM1:UPP:DATA 10.0",
        ]
        station.close()

    def test_a_setting_that_fails_leaves_the_instrument_closed(self):
        meter = {**NRX, "settings": {"averaging": "maybe"}}
        data = profile(power_meter_1=meter)
        links = []
        pool = TransportPool(lambda spec: links.append(FakeLink()) or links[-1])
        station = Station(station_from_dict(data), pause=time.sleep, pool=pool)
        with pytest.raises(InstrumentError, match="power_meter_1: averaging"):
            station.instrument("power_meter_1")
        assert not station.is_open("power_meter_1")
        assert pool.open_links == 0

    def test_a_power_sensor_gets_its_settings_in_the_order_it_couples_them(self):
        """A U2002H forgets everything when it is plugged in again; a count turns
        its auto averaging off and either turns averaging on, so auto on with
        averaging off holds only when written count, auto, averaging."""
        sensor = {
            "driver": "keysight.u2002h",
            "connection": {
                "kind": "visa",
                "resource": "USB0::0x0957::0x2D18::MY54260001::0::INSTR",
            },
            "settings": {
                "offset": -10.0,
                "averaging": False,
                "averaging_auto": True,
                "averaging_count": 64,
                "measurement_rate": "DOUB",
            },
        }
        station, link, _ = opened(profile(power_meter_2=sensor), "power_meter_2")
        assert link.written == [
            "SENS:AVER:COUN 64",
            "SENS:AVER:COUN:AUTO 1",
            "SENS:AVER:STAT 0",
            "SENS:MRAT DOUB",
            "SENS:CORR:GAIN2 -10.0",
        ]
        station.close()

    def test_a_simulator_starts_configured_as_the_profile_says(self):
        meter = {**NRX, "simulate": True, "settings": {"aperture_time": 0.3}}
        data = profile(power_meter_1=meter)
        with Station(station_from_dict(data), pause=time.sleep) as station:
            assert station.instrument("power_meter_1").get_aperture_time() == 0.3


class TestOldProfiles:
    def test_options_that_are_configuration_become_settings(self):
        meter = {**NRX, "options": {"aperture_time": 0.05, "averaging": False}}
        spec = station_from_dict(profile(power_meter_1=meter)).instruments[
            "power_meter_1"
        ]
        assert spec.options == {}
        assert spec.settings == {"aperture_time": 0.05, "averaging": False}

    def test_a_setting_kept_already_wins(self):
        meter = {
            **NRX,
            "options": {"aperture_time": 0.05},
            "settings": {"aperture_time": 0.2},
        }
        spec = station_from_dict(profile(power_meter_1=meter)).instruments[
            "power_meter_1"
        ]
        assert spec.settings == {"aperture_time": 0.2}

    def test_other_options_stay_options(self):
        # angle is a quantity of the rotator, but a setpoint, not configuration
        rotator = {"driver": "sim.rotator", "options": {"angle": 10.0}}
        unknown = {"driver": "acme.thing", "options": {"aperture_time": 1.0}}
        specs = station_from_dict(
            profile(rotator_1=rotator, thing_1=unknown)
        ).instruments
        assert specs["rotator_1"].options == {"angle": 10.0}
        assert specs["thing_1"].options == {"aperture_time": 1.0}

    def test_saved_again_as_settings(self):
        meter = {**NRX, "options": {"averaging": True}}
        saved = station_to_dict(station_from_dict(profile(power_meter_1=meter)))
        assert saved["instruments"]["power_meter_1"]["settings"] == {"averaging": True}
        assert "options" not in saved["instruments"]["power_meter_1"]
