# ThzDAQ: measuring with an agent

ThzDAQ runs a SIS mixer bench. A daemon holds the instruments; the person at the bench
watches the ThzDAQ window. You reach the bench through the MCP server `thzdaq` (its tools
below) or the command `thzdaq` in your shell. Both are clients of the same daemon: what you
do is seen in the window, and what you change waits for the person's consent.

## Rules

1. **Describe before you act.** `describe_device(ref)` lists what a device reads and takes:
   units, the range it accepts, the range beyond which a person is asked, steps and rate,
   and DANGER for a step that may harm it. `describe_procedure(procedure)` lists the
   parameters in the units they are typed in and the devices that suit each slot.
2. **Units.** Answers carry units (`2.3 mV`, `-45.1 dBm`). Type values with their unit:
   `"2.3mV"`, `"223 GHz"`, `"10 uA"`. A bare number is SI (V, A, Hz, s, K, Pa); power is in
   dBm, angles in degrees. Never guess a unit.
3. **Stay in the working range.** Do not set a value outside the range `describe_device`
   shows. A value beyond the limits is refused (`out_of_limits`) and nothing is sent; a
   large change goes in steps at the bench rate on its own: do not split it yourself to get
   around a question.
4. **Dangerous steps** (DANGER in a description: switching a bias off, writing a
   calibration) need a reason. Say it in words first (`ask_user`), then make the call; the
   window asks the person to type the device's name to allow it.
5. **What you change waits for the person.** `set_quantity`, `call_action` and
   `start_measurement` open a dialog in the window; the call waits up to 50 s. Reading,
   describing, waiting and cancelling need nobody.
   - Allowed: the call goes on, maybe with another value the person typed; the answer
     tells the value that was set.
   - Refused: the result is an error `denied: … not allowed: <their words>`. Read the
     words and do as they say. Do not repeat the same call.
   - `nobody answered in 50 s`: ask once more later, or ask in words (`ask_user`).
   - `no person can answer now`: the window is closed. Tell the user to open ThzDAQ (or run
     `thzdaq approvals watch` in a terminal) and wait; do not look for another way.
6. **Long measurements.** `start_measurement` returns at once with the run's number
   (`#12`). Then call `wait_measurement(id, timeout)` (at most 60 s) until it ends: it tells
   the progress while it waits and answers with a summary (records, the range of each
   column with its unit, results) and the file. `cancel_measurement(id)` stops a run: it
   restores what it changed. `dry_run: true` checks a start without running it.
7. **One sweep per device.** A device another measurement sweeps is refused (`conflict`).
   Share it (`share: true`) only when the person agrees: both measurements note it.
8. **Data.** Measurements of this folder go to its `data/` as JSON
   (`data/<date>/<number>_<procedure>.json`); `thzdaq show <file>` tells what one holds.
   Read the file to analyse it; never pass arrays through tools.
9. **Ask in words** when the plan is unclear: `ask_user(question, options)` shows the
   question in the window; still waiting after `timeout`, `wait_answer(id)` waits on.
10. **Raw commands** go to an instrument as typed, for what its driver does not wrap
    (`raw_command(instrument, command)`, `instrument` is its id in the profile, not a
    device on it). A query (with `?`, `*IDN?`) waits for the person like a set. A write
    is refused to agents whatever you are allowed: no limit checks it. When the bench
    needs one, say which command and why (`ask_user`); the person sends it.
11. **The bench's own measurements** (`custom.<name>`) are Python scripts in the bench's
    library (`measurements/` of the program's folder, `list_custom` names it). Read one
    (`read_custom`), check a change (`check_custom` with `text`) before you write it
    (`write_custom`: the person sees the change first), and run it with
    `start_measurement(procedure="custom.<name>", typed=..., devices=...)` as any
    procedure. The format is below.

## Tools of the MCP server `thzdaq`

| Tool | What it does |
|---|---|
| `list_devices`, `describe_device`, `read_device` | the devices, what they take, what they read now |
| `set_quantity(ref, key, value)` | set a value (with its unit); a person allows it |
| `call_action(ref, action, arguments)` | an action of a device (turn the load, read a trace) |
| `raw_command(instrument, command)` | a raw query (with `?`) to an instrument; a person allows it |
| `list_connections` | the connections the instruments share, open or broken |
| `list_procedures`, `describe_procedure` | what the bench measures and how a run would go |
| `start_measurement` | start a procedure; a person allows it |
| `wait_measurement`, `summarize_measurement` | follow a run, what it holds so far |
| `cancel_measurement`, `list_runs` | stop a run; the runs of the daemon |
| `list_custom`, `read_custom` | the bench's own measurements: their scripts |
| `check_custom(script, text)` | what is wrong with a script, by line; the form it declares |
| `write_custom(script, text)` | save a script of the library; a person allows it |
| `ask_user`, `wait_answer` | a question to the person at the bench |
| `get_daemon_status` | the daemon, its profile, clients, runs and problems |

Resources: `thzdaq://procedures`, `thzdaq://procedures/<name>`, `thzdaq://station` (the
profile; connections only by their kind) and `thzdaq://guide/<topic>` (this guide is
`agents`).

## Example: an I-V curve

1. `list_devices` → the SIS biases, e.g. `sis_bias_1`.
2. `describe_procedure(procedure="sis.iv_curve")` → `voltage`: a sweep in mV, default
   `0:7:351`; the slot `bias` takes `sis_bias_1` or `sis_bias_2`.
3. `start_measurement(procedure="sis.iv_curve", devices={"bias": "sis_bias_1"},
   typed={"voltage": "0:7:351"})` → the person allows it in the window →
   `#12 SIS I-V curve (sis.iv_curve): running, 0/351 steps`.
4. `wait_measurement(id=12, timeout=60)` until `completed` → the summary: table `iv`, 351
   records, `voltage` and `current` with their ranges, the file.
5. Read the file to find the gap, Rn and the rest.

## The command line

The same operations from your shell, with `--json` for answers to parse:
`thzdaq devices`, `thzdaq device sis_bias_1`, `thzdaq read sis_bias_1`,
`thzdaq set sis_bias_1 voltage_set 2.3mV`, `thzdaq procedures`,
`thzdaq describe sis.iv_curve`, `thzdaq raw sis_block_1 "*IDN?"`,
`thzdaq run sis.iv_curve --device bias=sis_bias_1 --set voltage=0:7:351` (follows the run
to its end; `--detach` only starts it), `thzdaq status`, `thzdaq cancel 12`,
`thzdaq show <file>`. In an agent's shell the command is the agent's (`cli:agent`): `--yes`
does not answer for the person, and what changes the bench waits for them as with MCP.

## Connecting an agent

`thzdaq agent-setup [<folder>]` writes into the folder `.mcp.json` (Claude Code),
`.codex/config.toml` (Codex), this guide as `AGENTS.md` and `CLAUDE.md` that takes it in.
The server is started by the absolute path of the `thzdaq` that wrote them (the build's
`thzdaq-cli.exe`, or the `thzdaq` of an environment) with `mcp --workspace <folder>`, so
measurements land in the folder's `data/`.

- Claude Code reads `.mcp.json` when it starts in the folder and asks once to trust the
  server.
- Codex reads `.codex/config.toml` of a trusted project only. Otherwise put the table into
  `~/.codex/config.toml`:

  ```toml
  [mcp_servers.thzdaq]
  command = "C:\\ThzDAQ\\thzdaq-cli.exe"
  args = ["mcp", "--workspace", "C:\\Users\\lab\\experiment"]
  tool_timeout_sec = 120  # a call waits up to 50 s for a person, a wait up to 60 s
  ```

`thzdaq --simulate agent-setup` points the agents at the simulator's daemon: a bench to
try things on without instruments.

## A measurement of the bench's own

A script whose top declares its form; the window, `thzdaq run custom.<name>` and
`start_measurement` give it the devices and values chosen. Each declaration is assigned
to a name (the slot or parameter of that name), all of them before `connect()`:

```python
"""P-V on both loads

IF power against bias on the hot and the cold load.
"""
from thzdaq import connect, device, plot, value

bias = device("SIS bias", kind="sis_bias")      # a slot: a SIS bias
detector = device("Detector", "PowerDetector")  # a slot: any power detector
load = device("Load", "LoadSwitch")
voltage = value("Bias voltage", "0:7:351", unit="mV")  # a sweep, typed in mV
settle = value("Settle", 10, unit="ms")                 # a number, given in s
pv = plot("P-V", table="pv", x="voltage", y="power", group_by="load")

lab = connect()
with lab.measurement("pv", devices=[bias, detector, load], exclusive=[bias]) as m:
    m.restore(bias, "voltage_set")        # the daemon sets it back however it ends
    m.on_exit(load, "to_cold")
    for state in ("hot", "cold"):
        getattr(load, f"to_{state}")()
        for v in m.sweep(voltage):        # stops at a cancel
            bias.voltage_set = v
            m.sleep(settle)
            m.record("pv", load=state, voltage=bias.read().voltage, power=detector.power)
            m.progress()
```

- `device(title, *capabilities, kind=...)`: the device chosen for the slot.
- `value(title, default, unit=..., minimum=..., maximum=..., choices=...)`: a number in
  SI (typed in `unit`), a sweep for `m.sweep`, true/false, a choice, a text or a list.
- `plot(title, table, x, y, group_by=..., kind="map", z=...)`: a plot known before the start.
- `instrument(id, driver="generic.scpi", connection="tcp://host:port", name=reading(...),
  other=setting(...))`: an instrument without a driver of its own, spoken to in raw
  commands. `reading(query, unit, parse, scale)` makes a value of an answer (`parse`: a
  regular expression, a dict of answers, a function; `scale` to SI), `setting(query,
  "CMD {:.6f}", unit, minimum, maximum)` writes one within its limits; `name.raw(cmd)`
  sends any command. Its first run puts the instrument into the profile once a person
  allows it, and a person allows its raw writes (then within the measurement they go on).
  Your scripts are refused both: write the script, then ask the person to run it once
  or to add the instrument in Setup → Add instrument → Generic (raw). Once it is in the
  profile as declared, your script may read it (raw queries are asked like a set).
- The first line of the docstring is its title. Records: one table per kind of point,
  every loop variable a column.
