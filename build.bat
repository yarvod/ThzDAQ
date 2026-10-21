@echo off
rem Windows build: dist\ThzDAQ (or dist\<name> with "build.bat <name>")
setlocal

if "%1"=="" (
    set "app_name=ThzDAQ"
) else (
    set "app_name=%1"
)

set "app_dir=.\dist\%app_name%"
set "stations_backup=.\dist\%app_name%_stations"

rem Keep bench profiles edited inside a previous build
if exist "%app_dir%\stations" xcopy /E /I /Y "%app_dir%\stations" "%stations_backup%" >nul

uv sync --locked
if errorlevel 1 exit /b %errorlevel%
uv run pyinstaller main.py -n "%app_name%" --onedir --icon=".\assets\logo2.png" --noconsole --windowed -y --add-data "assets;assets"
if errorlevel 1 exit /b %errorlevel%

rem Updater for in-app updates: standard library only, so a small one-file exe
uv run pyinstaller updater.py -n updater --onefile --noconsole -y --distpath .\build\updater_dist --workpath .\build\updater_work --specpath .\build
if errorlevel 1 exit /b %errorlevel%
copy /Y ".\build\updater_dist\updater.exe" "%app_dir%\updater.exe" >nul

xcopy /E /I /Y ".\stations" "%app_dir%\stations" >nul
if exist "%stations_backup%" xcopy /E /I /Y "%stations_backup%" "%app_dir%\stations" >nul

endlocal
