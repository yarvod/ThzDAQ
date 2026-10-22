#!/bin/bash
# Linux/macOS build: dist/ThzDAQ (and ThzDAQ.app on macOS)
set -e
app_name="${1:-ThzDAQ}"
uv sync --locked
uv run pyinstaller main.py -n "$app_name" --onedir --icon=assets/logo.png --noconsole -y \
    --add-data="assets:assets" --collect-data thzdaq_gui --collect-data qtawesome
# Bench profiles next to the executable; keep ones already edited there
mkdir -p "dist/$app_name/stations"
cp -n stations/*.yaml "dist/$app_name/stations/" 2>/dev/null || true
