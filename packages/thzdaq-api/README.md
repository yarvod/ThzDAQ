# thzdaq-api

The contract between the ThzDAQ bench daemon and its clients (GUI, CLI, MCP, scripts):
operations, data types, events and errors, and the client that calls the daemon. It
depends only on `msgspec`: no Qt, no numpy, no instrument drivers. See `docs/daemon.md`,
«Пакеты, слои и границы».
