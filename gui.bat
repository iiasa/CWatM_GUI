@echo off

setlocal
cd /d "%~dp0"

set "PYW=%~dp0venv\Scripts\pythonw.exe"
start "" "%PYW%" "%~dp0cwatm_gui.py" %*
endlocal
