"""A temperature controller's heater outputs are devices of the bench without
a profile entry: fixed channels of their own class beside its inputs, with
their quantities, the setpoint guarded by the passport of the real driver."""

import time

import pytest
from thzdaq_core.domain.station.config import InstrumentConfig, StationConfig
from thzdaq_core.domain.station.station import Station
from thzdaq_instruments.capabilities import Thermometer
from thzdaq_instruments.errors import LimitError
from thzdaq_instruments.temperature_controller import (
    HEATER_QUANTITIES,
    MANUAL_OUTPUT,
    SETPOINT,
)


@pytest.fixture
def station():
    controller = InstrumentConfig("lakeshore.336", simulate=True, title="Cryostat")
    with Station(StationConfig("bench", {"tc": controller}), pause=time.sleep) as s:
        yield s


def test_heater_outputs_are_devices_beside_the_inputs(station):
    devices = {info.ref: info for info in station.devices()}
    assert [ref for ref in devices if ref.startswith("tc:")] == [
        "tc:A", "tc:B", "tc:C", "tc:D", "tc:heater1", "tc:heater2",
    ]  # fmt: skip
    assert devices["tc:A"].provides(Thermometer)
    assert devices["tc:heater1"].capabilities == ()
    assert devices["tc:heater2"].title == "Cryostat heater2"
    keys = [q.key for q in station.quantities("tc:heater1")]
    assert keys == [q.key for q in HEATER_QUANTITIES]
    assert station.passport("tc:heater1")[MANUAL_OUTPUT.key].maximum == 100.0


def test_a_heater_is_set_through_the_guard(station):
    heater = station.device("tc:heater1")
    heater.write(SETPOINT, 7.5)
    assert heater.read([SETPOINT]) == {SETPOINT.key: 7.5}
    with pytest.raises(LimitError):
        heater.write(SETPOINT, -1.0)
    assert station.limit_problems("tc:heater2", MANUAL_OUTPUT.key, [120.0])
