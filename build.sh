#! /bin/bash

pyInstaller main.py -n SIS_manager --onedir --icon=./assets/logo.png --noconsole -y
mkdir ./dist/SIS_manager/assets
cp ./assets/* ./dist/SIS_manager/assets/