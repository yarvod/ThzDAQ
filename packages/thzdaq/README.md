# thzdaq

ThzDAQ controls a SIS mixer bench and measures it: bias, LO, IF power, temperatures,
I-V and noise-temperature measurements. A daemon holds the instruments; the window, the
`thzdaq` command, agents (Claude Code, Codex) and your scripts are its clients.

This package is the client: the `thzdaq` command and the library for scripts
(`from thzdaq import connect`). It is light, without instrument drivers or numpy.

```bash
uv tool install thzdaq          # the thzdaq command
uv add thzdaq                   # or pip install thzdaq: in your project or notebook
```

| Extra | What it adds |
|---|---|
| `thzdaq[analysis]` | analysis functions for your own calculations (numpy only) |
| `thzdaq[daemon]` | the bench daemon with instrument drivers: a bench on plain Python |
| `thzdaq[mcp]` | `thzdaq mcp`, the bench's tools for Claude Code and Codex |
| `thzdaq[gui]` | the ThzDAQ window (Python 3.11) |
| `thzdaq[all]` | all of the above |

The daemon serves only this machine. Without `thzdaq[daemon]` a client starts the
[ThzDAQ build](https://github.com/yarvod/ThzDAQ/releases) installed here (it notes
itself at its first start), or connects to the daemon already running. Take the version
of the build: `pip install thzdaq==<version>`; client and daemon check that they speak
the same contract.

```bash
thzdaq --simulate devices                 # instruments on simulators
thzdaq procedures                         # what can be measured
thzdaq run sis.current_vs_voltage --set voltage=0:7:351
```

```python
from thzdaq import connect

lab = connect()                      # finds the daemon, or starts it
bias = lab["sis_bias_1"]
bias.voltage_set = "2.3mV"           # = thzdaq set sis_bias_1 voltage_set 2.3mV
print(bias.read())                   # SI values that know their unit
run = lab.run("sis.current_vs_voltage", bias=bias, voltage="0:7:351")
run.wait()
iv = run.table("iv")
```

Documentation: [docs/daemon.md](https://github.com/yarvod/ThzDAQ/blob/master/docs/daemon.md)
(in Russian). The packages behind this one: `thzdaq-api` (contract and client),
`thzdaq-cli`, `thzdaq-analysis`, `thzdaq-core`, `thzdaq-instruments`, `thzdaq-daemon`,
`thzdaq-mcp`, `thzdaq-gui`; all of one release share its version.
