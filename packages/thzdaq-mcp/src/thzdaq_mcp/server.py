"""thzdaq mcp: the bench for an agent over MCP stdio, a client of the daemon.

Claude Code and Codex start it themselves (.mcp.json, .codex/config.toml). It
connects at the agent's first call (starting the daemon when none runs) as
mcp:<the name the agent gave in initialize>: what it changes waits for a
person in the ThzDAQ window, and a refusal comes back as text the agent reads.
A failed call is a result with isError and what to do instead, never a
protocol error.
"""

from pathlib import Path
from typing import Optional

import anyio
import mcp_types as types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError
from thzdaq_api import host
from thzdaq_api.approvals import ANSWER_S
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.origins import MCP_CLIENT
from thzdaq_api.remote import RemoteLab
from thzdaq_api.tools import by_name, tools
from thzdaq_api.workspace import chosen, expected_profile

from thzdaq_mcp import resources
from thzdaq_mcp.bench import Bench, Connect, Progress
from thzdaq_mcp.tools import definition

NAME = "thzdaq"
UNNAMED = "agent"  # a client that does not say its name

INSTRUCTIONS = (
    "The ThzDAQ bench: a SIS mixer and its instruments, held by a daemon a person "
    "watches in the ThzDAQ window. Describe before you act (describe_device, "
    "describe_procedure). Values come with their units; type yours with units "
    '("2.3 mV", "223 GHz"). What you set, call or start waits for the person\'s '
    f"consent (up to {ANSWER_S:g} s): a refusal carries their words, read them and "
    "do as they say. Start a measurement with start_measurement, then call "
    "wait_measurement until it ends. The guide thzdaq://guide/agents tells the rules."
)


def agent(ctx: ServerRequestContext) -> str:
    """The client's name from initialize (claude-code, codex-mcp-client)."""
    given = ctx.session.client_params
    return given.client_info.name if given is not None else UNNAMED


def progress_of(ctx: ServerRequestContext) -> Optional[Progress]:
    """How to tell the client how far a call is, when it asked to know."""
    if ctx.meta is None or ctx.meta.get("progress_token") is None:
        return None
    return ctx.session.report_progress


def failed(error: LabError) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(text=f"{error.code.value}: {error}")],
        is_error=True,
    )


def server(bench: Bench, workspace: Optional[Path]) -> Server:
    found = by_name(tools(lambda: workspace))

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[definition(tool) for tool in found.values()]
        )

    async def call_tool(
        ctx, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        tool = found.get(params.name)
        if tool is None:
            return failed(
                LabError(
                    ErrorCode.UNKNOWN_OPERATION,
                    f"No tool {params.name!r}",
                    f"known: {', '.join(found)}",
                )
            )
        try:
            args = tool.arguments(params.arguments or {})
            await bench.open(agent(ctx))
            text = await bench.run(tool, args, progress_of(ctx))
        except LabError as e:
            return failed(e)
        return types.CallToolResult(content=[types.TextContent(text=text)])

    async def list_resources(ctx, params) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=resources.listed())

    async def list_templates(ctx, params) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(
            resource_templates=resources.templates()
        )

    async def read_resource(
        ctx, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        try:
            await bench.open(agent(ctx))
            mime, text = await resources.read(bench, str(params.uri))
        except LabError as e:
            code = (
                types.INVALID_PARAMS
                if e.code == ErrorCode.NOT_FOUND
                else types.INTERNAL_ERROR
            )
            raise MCPError(code, str(e)) from None
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(uri=params.uri, mime_type=mime, text=text)
            ]
        )

    return Server(
        NAME,
        version=host.app_version(),
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_list_resource_templates=list_templates,
        on_read_resource=read_resource,
    )


def reach(simulate: bool, station: Optional[str] = None) -> Connect:
    """The daemon of the bench, or of its simulator; started when none runs,
    with the profile station."""

    def connect(origin: str) -> RemoteLab:
        return host.connect_or_start(simulate, station, origin, MCP_CLIENT)

    return connect


def serve(simulate: bool = False, workspace: Optional[str] = None) -> int:
    """Serve on stdin and stdout until the client closes them; measurements
    go to workspace, else to the nearest one up from the folder it was
    started in (thzdaq.toml), else to the program's."""
    folder = chosen(workspace)
    bench = Bench(reach(simulate, expected_profile(folder)))
    found = server(bench, folder)

    async def run() -> None:
        async with stdio_server() as (read, write):
            await found.run(read, write, found.create_initialization_options())

    try:
        anyio.run(run)
    finally:
        bench.close()
    return 0
