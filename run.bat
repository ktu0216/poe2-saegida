@echo off
rem Run overlay without a console window
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m poe2_overlay
