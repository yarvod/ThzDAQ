"""thzdaq mcp as an agent meets it: tools from the catalog, measurements started
and waited for with their progress, what it changes allowed or refused by a
person in the window (an MCP client in this process, the daemon served in a
thread on simulators)."""

import copy
from functools import partial

import anyio
import msgspec
import pytest
from lab_helpers import bodies
from thzdaq_api import catalog, guides
from thzdaq_api.daemon import GetDaemonStatus
from thzdaq_api.devices import SetQuantity
from thzdaq_api.events import ApprovalRequested
from thzdaq_api.measurements import ListRuns
from thzdaq_api.operation import Rights
from thzdaq_api.origins import GUI
from thzdaq_api.procedures import CURRENT_VS_VOLTAGE
from thzdaq_api.station import GetStation, UpdateStation

pytestmark = pytest.mark.anyio

FAST = {"settle_time": "0", "first_point_delay": "0"}
SAFETY = {
    "limits": {"sis_bias_1": {"voltage_set": {"min": -5e-3, "max": 5e-3}}},
    "safe_state": {},
}


def text(result) -> str:
    (content,) = result.content
    return content.text


def iv(points: int, settle: str = "0") -> dict:
    return {
        "procedure": CURRENT_VS_VOLTAGE,
        "devices": {"bias": "sis_bias_1"},
        "typed": {**FAST, "voltage": f"0:2:{points}", "settle_time": settle},
    }


async def answering(window, call, **answer):
    """The call, while the person in the window answers what it asks."""
    async with anyio.create_task_group() as group:
        group.start_soon(
            partial(anyio.to_thread.run_sync, partial(window.answer, **answer))
        )
        return await call


async def started(client, window, arguments) -> int:
    result = await answering(
        window, client.call_tool("start_measurement", arguments), allowed=True
    )
    assert not result.is_error, text(result)
    return int(text(result).split()[0].lstrip("#"))


async def test_the_tools_are_the_chosen_operations_of_the_catalog(connect):
    async with connect() as client:
        listed = (await client.list_tools()).tools
    names = {tool.name for tool in listed}
    assert {"list_devices", "set_quantity", "start_measurement", "wait_measurement",
            "summarize_measurement", "ask_user"} <= names  # fmt: skip
    for tool in listed:
        op = catalog.operation(tool.name)
        assert tool.description == catalog.description(op)
        assert tool.input_schema == msgspec.json.decode(
            msgspec.json.encode(catalog.tool_schema(op))
        )
        assert tool.input_schema["type"] == "object"
        assert tool.annotations.read_only_hint == (op.rights is Rights.READ)
        # Nothing an agent is never let do: a person's, or the daemon's
        assert op.rights not in (Rights.STATION, Rights.ANSWER, Rights.DAEMON)


async def test_values_come_with_their_units(connect, lab_as):
    lab_as(GUI).call(SetQuantity(ref="sis_bias_1", key="voltage_set", value="2.3mV"))
    async with connect() as client:
        read = await client.call_tool("read_device", {"ref": "sis_bias_1"})
    assert "voltage_set = 2.3 mV" in text(read)


async def test_a_measurement_is_started_waited_for_and_summarized(
    connect, window, tmp_path, lab_as
):
    async with connect() as client:
        run_id = await started(client, window, iv(5))
        waited = await client.call_tool(
            "wait_measurement", {"id": run_id, "timeout": 10}
        )
    told = text(waited)
    assert "completed, 5/5 steps" in told and "by mcp:claude-code" in told
    assert "table iv" in told and "5 records" in told
    assert "voltage_set (Voltage setpoint, V) 0 V..2 mV" in told
    (run,) = lab_as("test").call(ListRuns())
    assert run.path.startswith(str(tmp_path / "data"))  # the agent's folder


async def test_progress_is_told_while_waiting(connect, window):
    heard = []

    async def progress(done, total, message):
        heard.append((done, total))

    async with connect() as client:
        run_id = await started(client, window, iv(40, settle="0.02"))
        waited = await client.call_tool(
            "wait_measurement",
            {"id": run_id, "timeout": 10},
            progress_callback=progress,
        )
    assert "completed" in text(waited)
    assert len(heard) > 2 and heard[-1] == (40, 40)
    assert [done for done, _ in heard] == sorted(done for done, _ in heard)


async def test_a_cancelled_wait_leaves_the_measurement_running(connect, window, lab_as):
    async with connect() as client:
        run_id = await started(client, window, iv(200, settle="0.02"))
        with anyio.move_on_after(0.3):
            await client.call_tool("wait_measurement", {"id": run_id, "timeout": 30})
        assert lab_as("test").call(ListRuns())[0].status == "running"
        cancelled = await client.call_tool("cancel_measurement", {"id": run_id})
    assert not cancelled.is_error and f"#{run_id}" in text(cancelled)


async def test_an_agents_set_waits_for_the_window_and_goes_as_allowed(connect, window):
    async with connect() as client:
        result = await answering(
            window,
            client.call_tool(
                "set_quantity",
                {"ref": "sis_bias_1", "key": "voltage_set", "value": "2mV"},
            ),
            allowed=True,
            value="1.5 mV",
        )
    assert not result.is_error and text(result) == "sis_bias_1: voltage_set = 1.5 mV"
    assert window.heard  # the window was asked


async def test_a_refusal_reaches_the_agent_in_the_persons_words(connect, window):
    async with connect() as client:
        result = await answering(
            window,
            client.call_tool(
                "set_quantity",
                {"ref": "sis_bias_1", "key": "voltage_set", "value": "1mV"},
            ),
            allowed=False,
            text="check the pump first",
        )
    assert result.is_error
    assert text(result).startswith("denied:") and "check the pump first" in text(result)


async def test_an_agent_asks_raw_queries_and_never_writes(connect, window):
    async with connect() as client:
        query = await answering(
            window,
            client.call_tool(
                "raw_command", {"instrument": "sis_block_1", "command": "*IDN?"}
            ),
            allowed=True,
        )
        write = await client.call_tool(
            "raw_command",
            {"instrument": "sis_block_1", "command": "DEV4:OFF", "share": True},
        )
    assert not query.is_error
    assert text(query) == "sis_block_1 *IDN?: THZDAQ,SimSisBlock,0,1.0"
    assert write.is_error and text(write).startswith("denied:")
    assert len(bodies(window.heard, ApprovalRequested)) == 1  # the query alone


async def test_a_value_beyond_the_limits_is_refused_before_anybody_is_asked(
    connect, window
):
    profile = copy.deepcopy(window.lab.call(GetStation()).profile)
    window.lab.call(UpdateStation(profile={**profile, "safety": SAFETY}))
    async with connect() as client:
        result = await client.call_tool(
            "set_quantity",
            {"ref": "sis_bias_1", "key": "voltage_set", "value": "6 mV"},
        )
    assert result.is_error and text(result).startswith("out_of_limits:")
    assert not window.waiting()


async def test_mistakes_are_told_as_results(connect):
    async with connect() as client:
        unknown = await client.call_tool("update_station", {"profile": {}})
        mistyped = await client.call_tool("describe_device", {"device": "sis_bias_1"})
        missing = await client.call_tool("describe_device", {"ref": "nothing_1"})
    assert unknown.is_error and "No tool 'update_station'" in text(unknown)
    assert mistyped.is_error and text(mistyped).startswith("invalid_arguments:")
    assert missing.is_error and "no device 'nothing_1'" in text(missing)


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_the_origin_is_the_agents_name(connect, window, mode):
    async with connect(mode=mode, name="codex-mcp-client") as client:
        await started(client, window, iv(2))
    (asked,) = bodies(window.heard, ApprovalRequested)
    assert asked.approval.origin == "mcp:codex-mcp-client"
    # It listens as a client of its own kind: the window lists the agent
    clients = window.lab.call(GetDaemonStatus()).clients
    assert ("mcp", "mcp:codex-mcp-client") in {(c.kind, c.origin) for c in clients}


async def test_resources_tell_procedures_profile_and_guides(connect):
    async with connect() as client:
        listed = {str(r.uri) for r in (await client.list_resources()).resources}
        station = await client.read_resource("thzdaq://station")
        procedure = await client.read_resource(
            f"thzdaq://procedures/{CURRENT_VS_VOLTAGE}"
        )
        guide = await client.read_resource("thzdaq://guide/agents")
        tn = await client.read_resource("thzdaq://procedures/sis.y_factor_voltage")
    assert {
        "thzdaq://procedures",
        "thzdaq://station",
        "thzdaq://guide/agents",
    } <= listed
    profile = station.contents[0].text
    assert '"kind": "socket"' in profile and "169.254" not in profile  # no addresses
    assert "bias: sis_bias_1, sis_bias_2" in procedure.contents[0].text
    assert guide.contents[0].text == guides.guide(guides.AGENTS)
    # An old name finds the procedure; a field says when it is used
    text = tn.contents[0].text
    assert text.startswith("SIS Tn-V (sis.noise_temperature_vs_voltage)")
    assert "t_hot: Hot load" in text and "used only when hot_cold=true" in text


SCAN = '''"""Scan

A short bias sweep.
"""
from thzdaq import connect, device, value

bias = device("SIS bias", kind="sis_bias")
voltage = value("Bias voltage", "0:1:5", unit="mV")
lab = connect()
'''


async def test_an_agent_writes_checks_and_lists_the_benchs_own_measurements(
    connect, window, served
):
    async with connect() as client:
        empty = text(await client.call_tool("list_custom", {}))
        assert "no measurement of its own yet" in empty
        checked = await client.call_tool(
            "check_custom", {"script": "scan", "text": SCAN + "print(nothing)\n"}
        )
        assert "line 10 (names): undefined name 'nothing'" in text(checked)
        assert "voltage: Bias voltage, sweep, mV; default 0:1:5" in text(checked)
        written = await answering(
            window,
            client.call_tool("write_custom", {"script": "scan", "text": SCAN}),
            allowed=True,
        )
        assert not written.is_error and "no problems found" in text(written)
        assert window.heard  # the person saw the new script first
        listed = text(await client.call_tool("list_custom", {}))
        assert "scan: custom.scan, Scan" in listed
        read = text(await client.call_tool("read_custom", {"script": "scan"}))
        assert read.endswith(SCAN)
        procedures = text(await client.call_tool("list_procedures", {}))
        assert "custom.scan: Scan. A short bias sweep." in procedures
