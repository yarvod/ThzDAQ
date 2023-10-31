@echo off
setlocal

if "%1"=="" (
    set "app_name=SIS_manager"
) else (
    set "app_name=%1"
)

pyInstaller main.py -n %app_name% --onedir --icon=".\assets\logo.png" --noconsole --windowed -y
mkdir .\dist\%app_name%\assets
copy .\assets\* .\dist\%app_name%\assets\

endlocal
