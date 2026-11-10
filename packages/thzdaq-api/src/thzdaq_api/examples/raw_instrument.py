"""Instrument without a driver: a level swept by raw commands.

An instrument no driver knows, reached by its connection alone: the script
names its raw commands (a level written within its limits and read back,
the output switched on and off) and sweeps the level, each point a record
with its unit. Its first run asks a person to add the instrument to the
profile, and to allow raw writes in the measurement; then they go on their
own until it ends. A simulator answers a query with what was written.
"""

from thzdaq import connect, instrument, plot, setting, value

source = instrument(
    "source_1",
    driver="generic.scpi",  # text commands, no quantities of its own
    connection="tcp://169.254.0.60:5025",  # only this goes into the profile
    level=setting("VOLT?", "VOLT {:.6f}", unit="V", minimum=0, maximum=5),
    output=setting("OUTP?", "OUTP {}", parse={"ON": True, "OFF": False}),
)
level = value("Level", "0:5:51", unit="V")
settle = value("Settle", 20, unit="ms", help="after each step")
read_back = plot("Level read back", table="levels", x="set", y="level")

lab = connect()
print(source.raw("*IDN?"))  # any command as typed
with lab.measurement("level_sweep", devices=[source], total=level.points) as m:
    source.output = True
    try:
        for v in m.sweep(level):  # each step looks for a Stop
            source.level = v
            m.sleep(settle)
            m.record("levels", set=v, level=source.level, on=source.output)
            m.progress()
    finally:
        source.output = False

print(f"#{m.run.id} {m.run.status}: {m.run.path}")
