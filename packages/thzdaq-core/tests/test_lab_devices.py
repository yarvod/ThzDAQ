"""Device operations through LocalLab: what a client of the daemon gets."""

import pytest
from thzdaq_api import catalog
from thzdaq_api.devices import DescribeDevice, ListDevices, ReadDevice, SetQuantity
from thzdaq_api.errors import ErrorCode, LabError


def test_every_operation_has_its_handler(lab):
    assert not lab.dispatcher.missing()


def test_devices_are_listed_with_their_type(lab):
    devices = {d.ref: d for d in lab.call(ListDevices())}
    bias, supply = devices["sis_bias_1"], devices["power_supply_1"]
    assert (bias.kind, bias.type, bias.instrument) == (
        "sis_bias",
        "sis_bias",
        "sis_block_1",
    )
    assert bias.configured and "VoltageSource" in bias.capabilities
    assert (supply.kind, supply.type) == ("instrument", "power_supply")
    channel = devices["power_supply_1:1"]
    assert channel.kind == "channel" and channel.channel == "1"


def test_a_device_describes_its_quantities(lab):
    description = lab.call(DescribeDevice(ref="sis_bias_1"))
    quantities = {q.key: q for q in description.quantities}
    assert quantities["voltage_set"].settable and quantities["voltage_set"].unit == "V"
    assert quantities["current"].readable and not quantities["current"].settable
    # Shown in mV or µA: the prefixes of its unit come with it
    assert {"m", "µ"} <= {p.name for p in quantities["current"].prefixes}
    assert quantities["active"].prefixes == ()
    assert description.device.driver == "scontel.sis_block"
    # The offsets it keeps in the profile, described as values
    offsets = {s.key: s for s in description.settings}
    assert set(offsets) == {"offset_voltage", "offset_current"}
    assert (
        offsets["offset_voltage"].unit == "V" and offsets["offset_voltage"].persistent
    )
    assert not lab.call(DescribeDevice(ref="power_supply_1:1")).settings


def test_a_value_set_with_its_unit_reads_back(lab):
    done = lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="2.3mV"))
    assert done.value == pytest.approx(2.3e-3)
    reading = lab.call(ReadDevice(ref="sis_bias_1", keys=("voltage_set", "voltage")))
    assert reading.values["voltage_set"] == pytest.approx(2.3e-3)
    assert set(reading.values) == {"voltage_set", "voltage"}


@pytest.mark.parametrize(
    "operation, code",
    [
        (ReadDevice(ref="sis_bias_9"), ErrorCode.NOT_FOUND),
        (SetQuantity(ref="sis_bias_1", key="volts", value=1.0), ErrorCode.NOT_FOUND),
        (
            SetQuantity(ref="sis_bias_1", key="current", value=1.0),
            ErrorCode.NOT_ALLOWED,
        ),
        (
            SetQuantity(ref="sis_bias_1", key="voltage_set", value="2.3 mA"),
            ErrorCode.INVALID_ARGUMENTS,
        ),
    ],
)
def test_failures_say_what_is_wrong(lab, operation, code):
    with pytest.raises(LabError) as caught:
        lab.call(operation)
    assert caught.value.code == code


def test_operations_arrive_as_json(lab):
    with pytest.raises(LabError) as caught:
        lab.dispatcher.dispatch_json("read_device", b'{"ref": 5}', "test")
    assert caught.value.code == ErrorCode.INVALID_ARGUMENTS
    with pytest.raises(LabError) as caught:
        lab.dispatcher.dispatch_json("reboot_bench", b"{}", "test")
    assert caught.value.code == ErrorCode.UNKNOWN_OPERATION
    assert catalog.operation("list_devices") is ListDevices
