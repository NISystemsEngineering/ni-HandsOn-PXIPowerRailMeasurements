@echo off
REM ============================================================
REM   Beacon Exercise (no trigger) - Flash and Monitor
REM   (clean-machine version: standalone esptool.exe + esp-idf-monitor)
REM ============================================================
REM   EDIT THIS ONE LINE PER STATION:
SET PORT=COM10
REM ============================================================

SET ESPTOOL=%~dp0tools\esptool.exe
SET PROJECT_DIR=%~dp0exercises\beacon\build

title Beacon Exercise - No Trigger (%PORT%)

if not exist "%PROJECT_DIR%\flash_args" (
    echo.
    echo *** No build found at %PROJECT_DIR% ***
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"

echo Flashing to %PORT% ...
"%ESPTOOL%" --chip esp32c6 -p %PORT% -b 460800 write_flash @flash_args
if errorlevel 1 (
    echo.
    echo *** Flash failed. Check PORT and connections. ***
    pause
    exit /b 1
)

echo.
echo Opening monitor on %PORT% ...
echo Press Ctrl+] to exit the monitor when finished.
echo.
idf-monitor -p %PORT% -b 115200 --target esp32c6

echo.
echo Monitor closed.
pause
