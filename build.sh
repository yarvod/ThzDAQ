#! /bin/bash

pyInstaller main.py -n SIS_manager --onedir --icon=assets/logo.png --noconsole -y

mkdir ./dist/SIS_manager/assets
cp ./assets/* ./dist/SIS_manager/assets/
cp settings.ini ./dist/SIS_manager/

mkdir ./dist/SIS_manager.app/Contents/MacOS/assets
cp ./assets/* ./dist/SIS_manager.app/Contents/MacOS/assets/
cp settings.ini ./dist/SIS_manager.app/Contents/MacOS/