# thzdaq-api

The contract between the ThzDAQ bench daemon and its clients (GUI, CLI, MCP, scripts):
operations, data types, events and errors, and the client that calls the daemon. It
depends only on `msgspec`: no Qt, no numpy, no instrument drivers. Install it with
[`thzdaq`](https://pypi.org/project/thzdaq/); see
[docs/daemon.md](https://github.com/yarvod/ThzDAQ/blob/master/docs/daemon.md),
«Пакеты, слои и границы».
