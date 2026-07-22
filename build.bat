@echo off
setlocal

if "%1"=="" (
    set "app_name=SIS_manager"
) else (
    set "app_name=%1"
)

set "app_dir=.\dist\%app_name%"
set "settings_backup=.\dist\%app_name%_settings"

if exist "%app_dir%\dumps\*" (
    if not exist ".\dist\dumps" mkdir ".\dist\dumps"
    copy /Y "%app_dir%\dumps\*" ".\dist\dumps\" >nul
)

if exist "%app_dir%\settings.ini" (
    if not exist "%settings_backup%" mkdir "%settings_backup%"
    copy /Y "%app_dir%\settings.ini" "%settings_backup%\settings.ini" >nul
)

uv run pyinstaller main.py -n "%app_name%" --onedir --icon=".\assets\logo2.png" --noconsole --windowed -y
if errorlevel 1 exit /b %errorlevel%

if not exist "%app_dir%\assets" mkdir "%app_dir%\assets"
copy /Y ".\assets\*" "%app_dir%\assets\" >nul
copy /Y ".\settings_default.ini" "%app_dir%\settings_default.ini" >nul

if exist "%settings_backup%\settings.ini" (
    copy /Y "%settings_backup%\settings.ini" "%app_dir%\settings.ini" >nul
)

if exist ".env" (
    copy /Y ".env" "%app_dir%\.env" >nul
)

endlocal
