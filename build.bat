@echo off
setlocal

if "%1"=="" (
    set "app_name=SIS_manager"
) else (
    set "app_name=%1"
)

pyInstaller main.py -n %app_name% --onedir --icon=".\assets\logo2.png" --noconsole --windowed -y --add-data="assets:assets" --add-data="settings.ini:."

endlocal
