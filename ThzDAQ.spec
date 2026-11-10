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

from PyInstaller.utils.hooks import collect_data_files, collect_entry_point

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

window = Analysis(["main.py"], datas=datas)
# Commands that packages add to the command line (thzdaq mcp) are found by
# their entry points: their metadata and modules go in with the guides for
# agents that thzdaq_api keeps
commands, modules = collect_entry_point("thzdaq.cli")
cli = Analysis(
    ["cli_main.py"],
    datas=commands + collect_data_files("thzdaq_api"),
    hiddenimports=modules,
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
