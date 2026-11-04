@echo off
rem Demo B: rail droop statistics (C#).
rem Uses its own location, so it works wherever the repo is cloned.
set "EXE=%~dp0Transient_Analysis\release\PdnDroopDemo.exe"
if not exist "%EXE%" (
    echo PdnDroopDemo.exe was not found at:
    echo %EXE%
    echo Build PdnDroopDemo.sln in Visual Studio first.
    pause
    exit /b 1
)
start "" "%EXE%"
