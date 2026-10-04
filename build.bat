@echo off
rem Build exe: dist\poe2-saegida\poe2-saegida.exe
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -q pyinstaller || exit /b 1
".venv\Scripts\python.exe" tools\make_icon.py || exit /b 1
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name poe2-saegida ^
  --icon build\icon.ico ^
  --add-data "guides;guides" ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtPdf ^
  run_overlay.py
