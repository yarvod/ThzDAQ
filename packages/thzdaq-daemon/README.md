# thzdaq-daemon

The bench daemon: the server-side composition root (station, stores, use cases) and the
HTTP + SSE transport of the `thzdaq-api` contract, with its process lifecycle. It has no
operation logic of its own. Install it as `thzdaq[daemon]`; see
[docs/daemon.md](https://github.com/yarvod/ThzDAQ/blob/master/docs/daemon.md).
