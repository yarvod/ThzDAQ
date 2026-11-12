"""The tools of thzdaq_api.tools as MCP describes them to an agent: the
operation's name, its docstring and the JSON schema of its arguments, and
whether it only reads."""

import mcp_types as types
from thzdaq_api.tools import Tool


def definition(tool: Tool) -> types.Tool:
    return types.Tool(
        name=tool.name,
        description=tool.description(),
        input_schema=tool.schema(),
        annotations=types.ToolAnnotations(
            read_only_hint=tool.reads, destructive_hint=False
        ),
    )
