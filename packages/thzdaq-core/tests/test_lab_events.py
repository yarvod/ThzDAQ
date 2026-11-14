"""Events, the snapshot and polling through LocalLab."""

import time

import pytest
from thzdaq_api.devices import CancelPoll, SetQuantity, SubscribePoll
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import GetSnapshot, QuantitySet, Resync, Values
from lab_helpers import bodies, wait_for
from thzdaq_core.application.events import EventBus


def test_a_set_is_an_event_with_who_and_from_what(lab):
    heard = []
    lab.subscribe(heard.append)
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="2mV"))
    first, second = bodies(heard, QuantitySet)
    assert first.origin == "test" and first.value == pytest.approx(1e-3)
    assert second.before == pytest.approx(1e-3) and second.value == pytest.approx(2e-3)
    assert heard[1].seq == heard[0].seq + 1


def test_a_snapshot_and_the_events_after_it_miss_nothing(lab):
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    snapshot = lab.call(GetSnapshot())
    assert snapshot.values["sis_bias_1"]["voltage_set"] == pytest.approx(1e-3)
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="2mV"))
    heard = []
    lab.subscribe(heard.append, since=snapshot.seq)  # subscribed late
    assert [event.seq for event in heard] == [snapshot.seq + 1]
    assert heard[0].body.value == pytest.approx(2e-3)


def test_a_client_behind_the_buffer_takes_a_new_snapshot():
    bus = EventBus(capacity=2)
    for value in range(5):
        bus.publish(QuantitySet("x", "y", value))
    heard = []
    bus.subscribe(heard.append, since=1)
    assert [type(event.body) for event in heard] == [Resync]
    heard.clear()
    bus.subscribe(heard.append, since=3)  # still in the buffer
    assert [event.seq for event in heard] == [4, 5]


def test_what_a_listener_missed_comes_before_what_is_published_meanwhile():
    """A run publishes from its own thread while a window that reconnects is
    told what it missed: the newer event waits, or the window would take it
    first and drop the older ones as already heard."""
    import threading

    bus = EventBus()
    for _ in range(3):
        bus.publish(Resync())
    heard = []
    meanwhile = threading.Thread(target=lambda: bus.publish(Resync()))

    def listener(event):
        heard.append(event.seq)
        if len(heard) == 1:  # while what it missed is told
            meanwhile.start()
            meanwhile.join(0.2)  # published at once, unless it waits its turn

    bus.subscribe(listener, since=0)
    meanwhile.join(5)
    assert heard == [1, 2, 3, 4]


def test_one_poll_per_device_at_the_shortest_interval(lab):
    heard = []
    lab.subscribe(heard.append)
    slow = lab.call(SubscribePoll(ref="power_meter_1", interval=0.5))
    fast = lab.call(SubscribePoll(ref="power_meter_1", interval=0.02, keys=("power",)))
    polling = lab.assembled.polling
    # One poll for both: the shortest interval, every key since one wants all
    assert polling.status() == {"power_meter_1": (0.02, None, 2)}
    wait_for(lambda: len(bodies(heard, Values)) >= 3)
    assert {v.ref for v in bodies(heard, Values)} == {"power_meter_1"}
    assert "power" in bodies(heard, Values)[-1].values
    lab.call(CancelPoll(id=slow.id))
    assert polling.status() == {"power_meter_1": (0.02, ("power",), 1)}
    lab.call(CancelPoll(id=fast.id))
    assert polling.status() == {}
    time.sleep(0.05)  # a read already under way may still report
    count = len(bodies(heard, Values))
    time.sleep(0.1)
    assert len(bodies(heard, Values)) == count
    with pytest.raises(LabError) as caught:
        lab.call(CancelPoll(id=fast.id))
    assert caught.value.code == ErrorCode.NOT_FOUND


@pytest.mark.parametrize(
    "poll, code",
    [
        (SubscribePoll(ref="power_meter_1", interval=0), ErrorCode.INVALID_ARGUMENTS),
        (
            SubscribePoll(ref="power_meter_1", interval=1, keys=("volume",)),
            ErrorCode.NOT_FOUND,
        ),
        (SubscribePoll(ref="power_meter_9", interval=1), ErrorCode.NOT_FOUND),
    ],
)
def test_a_poll_that_cannot_run_is_refused(lab, poll, code):
    with pytest.raises(LabError) as caught:
        lab.call(poll)
    assert caught.value.code == code
