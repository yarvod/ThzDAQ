#! /bin/bash

pyInstaller main.py -n SIS_manager --onedir --icon=assets/logo.png --noconsole -y --add-data="assets:assets" --add-data="settings.ini:."
