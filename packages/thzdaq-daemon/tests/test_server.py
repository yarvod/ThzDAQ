"""The HTTP + SSE server: who may talk, how failures travel, how a stream
catches up."""

import http.client
import socket

import pytest
from lab_helpers import bodies, wait_for
from thzdaq_api import wire
from thzdaq_api.daemon import GetDaemonStatus
from thzdaq_api.devices import SetQuantity
from thzdaq_api.errors import ErrorCode
from thzdaq_api.events import GetSnapshot, QuantitySet, Resync
from thzdaq_api.transport import LOCALHOST, TOKEN, bearer, request
from thzdaq_daemon.server import HTTP_STATUS


def test_every_failure_has_an_http_status():
    assert set(HTTP_STATUS) == set(ErrorCode)


def raw(served, path, headers, method="GET"):
    connection = http.client.HTTPConnection(LOCALHOST, served.server.port, timeout=5)
    connection.putrequest(method, path, skip_host=True)
    for name, value in headers.items():
        connection.putheader(name, value)
    connection.endheaders()
    response = connection.getresponse()
    return response.status, response.read()


@pytest.mark.parametrize(
    "headers, code",
    [
        ({}, ErrorCode.UNAUTHORIZED),
        ({TOKEN: "Bearer guess"}, ErrorCode.UNAUTHORIZED),
        ({TOKEN: None, "Host": "evil.example:80"}, ErrorCode.NOT_ALLOWED),
        ({TOKEN: None, "Origin": "http://evil.example"}, ErrorCode.NOT_ALLOWED),
    ],
    ids=["no token", "wrong token", "foreign host", "a web page"],
)
def test_only_a_client_with_the_token_talks(served, headers, code):
    sent = {"Host": f"{LOCALHOST}:{served.server.port}", **headers}
    if TOKEN in sent and sent[TOKEN] is None:
        sent[TOKEN] = bearer(served.server.token)
    status, data = raw(served, "/ops/get_snapshot", sent, "POST")
    assert status == HTTP_STATUS[code]
    assert wire.decode_failure(data).code == code


def test_failures_travel_with_their_code(served):
    host = served.host
    status, _, data = request(host.port, host.token, "POST", "/ops/reboot_bench", b"{}")
    assert status == 404
    assert wire.decode_failure(data).code == ErrorCode.UNKNOWN_OPERATION
    status, _, data = request(host.port, host.token, "GET", "/nowhere")
    assert status == 404 and wire.decode_failure(data).code == ErrorCode.NOT_FOUND


def test_a_listener_is_a_client_with_a_heartbeat(lab, served):
    lab.subscribe(lambda event: None)
    assert lab.heartbeat is not None and lab.heartbeat.clients == 1
    (client,) = lab.call(GetDaemonStatus()).clients
    assert (client.kind, client.origin) == ("test", "test")


def test_a_broken_stream_reconnects_and_hears_what_it_missed(lab):
    heard = []
    lab.subscribe(heard.append)
    lab.call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="1mV"))
    (stream,) = lab._streams
    stream._socket.shutdown(socket.SHUT_RDWR)  # the connection breaks
    lab.assembled.events.publish(QuantitySet("sis_bias_1", "voltage_set", 2e-3))
    wait_for(lambda: len(bodies(heard, QuantitySet)) == 2)
    assert [e.seq for e in heard] == list(range(heard[0].seq, heard[0].seq + 2))


def test_a_stream_behind_the_buffer_gets_resync(lab):
    since = lab.call(GetSnapshot()).seq
    for value in range(10001):  # more than the buffer keeps
        lab.assembled.events.publish(QuantitySet("x", "y", value))
    heard = []
    lab.subscribe(heard.append, since=since)
    assert [type(event.body) for event in heard] == [Resync]


def test_ten_thousand_events_arrive_in_order_and_fast(lab):
    import time

    heard = []
    lab.subscribe(heard.append)
    started = time.monotonic()
    for value in range(10000):
        lab.assembled.events.publish(QuantitySet("x", "y", value))
    wait_for(lambda: len(heard) == 10000, timeout=10)
    assert time.monotonic() - started < 5
    assert [e.body.value for e in heard] == list(range(10000))
    assert [e.seq for e in heard] == list(range(heard[0].seq, heard[0].seq + 10000))
