#! /bin/bash

pyInstaller main.py -n SIS_manager --onedir --icon=./assets/logo.ico --noconsole -y
mkdir ./dist/SIS_manager/assets
cp ./assets/* ./dist/SIS_manager/assets/
cp settings.ini ./dist/SIS_manager/
