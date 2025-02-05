@echo off
setlocal

if "%1"=="" (
    set "app_name=SIS_manager"
) else (
    set "app_name=%1"
)

copy .\dist\%app_name%\dumps\ .\dist\dumps\
copy .\dist\%app_name%\settings.ini .\dist\%app_name%_settings\

pyInstaller main.py -n %app_name% --onedir --icon=".\assets\logo2.png" --noconsole --windowed -y
mkdir .\dist\%app_name%\assets
copy .\assets\* .\dist\%app_name%\assets\
copy .\settings_default.ini .\dist\%app_name%\
copy .\dist\%app_name%_settings\settings.ini .\dist\%app_name%\
copy .env .\dist\%app_name%\

endlocal
