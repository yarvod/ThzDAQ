# thzdaq-gui

The ThzDAQ window (PySide6, Qt Advanced Docking, pyqtgraph): a client of the bench daemon
through `thzdaq-api`, like the `thzdaq` command and the MCP server. It starts the daemon
it needs: the one of `thzdaq[daemon]` in the same environment, or the ThzDAQ build
installed on this machine. Install it as `thzdaq[gui]` (Python 3.11).

```bash
thzdaq gui                                               # the window in the workspace here
thzdaq-gui --station stations/2sb.example.yaml --simulate
```

See [ThzDAQ](https://github.com/yarvod/ThzDAQ).
