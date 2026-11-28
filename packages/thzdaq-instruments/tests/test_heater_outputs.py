"""The heater outputs of a temperature controller, on the LakeShore 336 (its
protocol emulated) and on its simulator alike: fixed channels of their own
class beside the inputs, their quantities read and set by their declarations,
as a dock and the daemon use them."""

import pytest
from emulators import LakeShoreEmulator
from thzdaq_instruments import default_registry
from thzdaq_instruments.capabilities import Thermometer
from thzdaq_instruments.drivers import HeaterOutput, LakeShore336, TemperatureInput
from thzdaq_instruments.limits import Limit
from thzdaq_instruments.parts import quantities_of, read_values
from thzdaq_instruments.sim import SimHeaterOutput, SimTemperatureController
from thzdaq_instruments.temperature_controller import HEATER_QUANTITIES, HEATERS


def lakeshore():
    transport, _ = LakeShoreEmulator().transport()
    return LakeShore336(transport)


CONTROLLERS = {"lakeshore": lakeshore, "sim": SimTemperatureController}
SET = {
    "heater_range": "low",
    "control_mode": "open loop",
    "control_input": "B",
    "setpoint": 12.5,
    "manual_output": 30.0,
    "pid_p": 80.0,
    "pid_i": 15.0,
    "pid_d": 5.0,
}


def test_heater_outputs_are_fixed_channels_of_their_own_class():
    assert LakeShore336.fixed_channels() == ("A", "B", "C", "D", "heater1", "heater2")
    assert LakeShore336.channel_class_of("B") is TemperatureInput
    assert LakeShore336.channel_class_of("heater2") is HeaterOutput
    assert SimTemperatureController.channel_class_of("heater1") is SimHeaterOutput
    controller = lakeshore()
    assert [type(c) for c in controller.channels][-2:] == [HeaterOutput] * 2
    assert controller.channel("heater2").output == 2
    info = default_registry().get(LakeShore336.driver_key)
    assert info.channel_capabilities == (Thermometer,)


def test_the_passport_of_a_heater_output():
    assert LakeShore336.passport("heater1") == {
        "setpoint": Limit(minimum=0.0),
        "manual_output": Limit(0.0, 100.0),
    }
    assert LakeShore336.passport("A") == {}


@pytest.mark.parametrize("key", HEATERS)
@pytest.mark.parametrize("make", CONTROLLERS.values(), ids=list(CONTROLLERS))
def test_a_heater_reads_and_sets_its_quantities(make, key):
    heater = make().channel(key)
    quantities = {q.key: q for q in quantities_of(heater)}
    assert list(quantities) == [q.key for q in HEATER_QUANTITIES]
    assert set(read_values(heater)) == set(quantities)
    for name, value in SET.items():
        quantity = quantities[name]
        quantity.write(heater, quantity.parse(value))
    values = read_values(heater)
    for name, value in SET.items():
        assert values[name] == (
            pytest.approx(value) if isinstance(value, float) else value
        )
    assert values["heater_status"] == "ok"
    assert quantities["setpoint"].setters == ("set_setpoint",)
    for name, bad in (("heater_range", "max"), ("pid_d", 250), ("pid_p", 0)):
        with pytest.raises(ValueError):
            quantities[name].parse(bad)


def test_the_simulated_heater_follows_its_mode():
    controller = SimTemperatureController(temperatures={"A": 4.0})
    heater = controller.channel("heater1")
    assert heater.get_output() == 0.0  # off as it starts
    by_key = {q.key: q for q in quantities_of(heater)}
    for name, value in (
        ("heater_range", "high"), ("control_mode", "closed loop PID"),
        ("control_input", "A"), ("setpoint", 5.0), ("pid_p", 30.0),
    ):  # fmt: skip
        by_key[name].write(heater, value)
    assert heater.get_output() == pytest.approx(30.0)  # P times 1 K below
    by_key["control_mode"].write(heater, "open loop")
    by_key["manual_output"].write(heater, 12.0)
    assert heater.get_output() == 12.0
    by_key["heater_range"].write(heater, "off")
    assert heater.get_output() == 0.0
