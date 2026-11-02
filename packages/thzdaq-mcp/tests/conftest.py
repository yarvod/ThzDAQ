import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).parents[2]
sys.path.insert(0, str(TESTS / "thzdaq-daemon" / "tests"))  # served
sys.path.insert(0, str(TESTS / "thzdaq-core" / "tests"))  # lab_helpers

AGENT = "claude-code"


@pytest.fixture
def anyio_backend():
    return "asyncio"  # the backend the stdio server runs on


@pytest.fixture
def served(tmp_path):
    """The simulated example bench's daemon, served in this process over HTTP."""
    from served import Served

    served = Served(tmp_path)
    yield served
    served.close()


@pytest.fixture
def lab_as(served):
    """The served daemon called as another client: lab_as("gui") is a window."""
    from thzdaq_api.remote import RemoteLab

    labs = []

    def remote(origin):
        labs.append(RemoteLab(served.host, origin, origin.split(":")[0]))
        return labs[-1]

    yield remote
    for opened in labs:
        opened.close()


@pytest.fixture
def window(lab_as):
    """A person's window on the daemon: it hears what waits and answers it."""
    from lab_helpers import Window
    from thzdaq_api.origins import GUI

    window = Window(lab_as(GUI))
    yield window
    window.stop()


@pytest.fixture
def mcp_server(served, tmp_path):
    """The MCP server on the served daemon; measurements go to tmp_path."""
    from thzdaq_api.origins import MCP_CLIENT
    from thzdaq_api.remote import RemoteLab
    from thzdaq_mcp.bench import Bench
    from thzdaq_mcp.server import server

    bench = Bench(lambda origin: RemoteLab(served.host, origin, MCP_CLIENT))
    yield server(bench, tmp_path)
    bench.close()


@pytest.fixture
def connect(mcp_server):
    """An agent's client of the server, in this process: connect() as claude-code,
    connect(mode="auto") speaking the stateless 2026-07-28 protocol."""
    import mcp_types as types
    from mcp import Client

    def client(mode="legacy", name=AGENT):
        return Client(
            mcp_server,
            mode=mode,
            client_info=types.Implementation(name=name, version="1"),
        )

    return client
