@echo off
rem 콘솔 창 없이 오버레이 실행
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m poe2_overlay
