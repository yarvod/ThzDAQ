#!/bin/bash
# Linux/macOS build: dist/ThzDAQ (and ThzDAQ.app on macOS)
set -e
app_name="${1:-ThzDAQ}"
uv sync --locked
# ThzDAQ (the window; --serve: the daemon) and thzdaq-cli in one folder
uv run pyinstaller ThzDAQ.spec -y -- --folder "$app_name"
# Bench profiles next to the executable; keep ones already edited there
mkdir -p "dist/$app_name/stations"
cp -n stations/*.yaml "dist/$app_name/stations/" 2>/dev/null || true
