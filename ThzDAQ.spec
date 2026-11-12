# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build (build.bat, build.sh): two programs over one _internal folder.

ThzDAQ.exe is windowed: the window, and with --serve the daemon its clients
start. thzdaq-cli.exe is a console program: the command line, MCP over stdio.
Windows gives a program either a console or none, as python.exe and
pythonw.exe. The program names are fixed (thzdaq_api.host.PROGRAM finds the
daemon by its name); the folder takes the name given after --:

    pyinstaller ThzDAQ.spec -y -- --folder ThzDAQ
"""

import argparse
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_entry_point,
    collect_submodules,
)

options = argparse.ArgumentParser()
options.add_argument("--folder", default="ThzDAQ")
folder = options.parse_args().folder

# Drawn by assets/make_icon.py: every size in the .ico, the .icns for macOS
icon = "assets/thzdaq.ico" if sys.platform == "win32" else "assets/thzdaq.icns"
datas = [("assets", "assets")]
datas += collect_data_files("thzdaq_gui")
datas += collect_data_files("qtawesome")
# The script editor completes by jedi: its stubs and parso's grammars are data
datas += collect_data_files("jedi") + collect_data_files("parso")

# A console's kernel is started by jupyter_client, which finds how to start
# one by its entry points: their metadata and modules go in
provisioners, provisioner_modules = collect_entry_point(
    "jupyter_client.kernel_provisioners"
)
window = Analysis(
    ["main.py"], datas=datas + provisioners, hiddenimports=provisioner_modules
)
# Commands that packages add to the command line (thzdaq mcp) are found by
# their entry points: their metadata and modules go in with the guides for
# agents that thzdaq_api keeps
commands, modules = collect_entry_point("thzdaq.cli")
# The kernel of a console runs as thzdaq-cli run-script -m thzdaq_api.kernel:
# IPython's kernel and what it imports only when asked. Without debugpy (it
# reads its own sources from disk): the kernel runs without Jupyter's debugger
kernel = ["thzdaq_api.kernel", *collect_submodules("ipykernel")]
# What scripts and consoles import, which the command line itself does not:
# ours with all their modules, the standard library (script_modules.py)
sys.path.insert(0, SPECPATH)
import script_modules  # noqa: E402

scripts = [
    module
    for name in (*script_modules.OURS, *script_modules.standard())
    for module in collect_submodules(name, filter=lambda m: not script_modules.a_test(m))
]
cli = Analysis(
    ["cli_main.py"],
    datas=commands + collect_data_files("thzdaq_api") + collect_data_files("ipykernel"),
    hiddenimports=modules + kernel + scripts,
    excludes=["debugpy"],
)


def program(analysis, name, console):
    return EXE(
        PYZ(analysis.pure),
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=console,
        icon=[icon],
    )


programs = COLLECT(
    program(window, "ThzDAQ", console=False),
    program(cli, "thzdaq-cli", console=True),
    window.binaries,
    window.datas,
    cli.binaries,
    cli.datas,
    name=folder,
)
if sys.platform == "darwin":
    BUNDLE(programs, name=f"{folder}.app", icon=icon)
