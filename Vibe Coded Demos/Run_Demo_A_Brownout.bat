@echo on
rem Demo A: brownout threshold sweep (Python).
rem Uses its own location, so it works wherever the repo is cloned.
cd /d "%~dp0Brownout_Threshold"
python brownout_voltage_gui.py
rem Keep the window open if Python reports an error.
if errorlevel 1 pause
