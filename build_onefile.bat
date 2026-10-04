@echo off
rem Build a single exe: dist_onefile\poe2-overlay.exe (release asset; slower start, guides are not editable)
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -q pyinstaller || exit /b 1
".venv\Scripts\python.exe" tools\make_icon.py || exit /b 1
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed --name poe2-overlay ^
  --icon "%~dp0build\icon.ico" ^
  --add-data "%~dp0guides;guides" ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtPdf ^
  --distpath "%~dp0dist_onefile" --workpath "%~dp0build_onefile" --specpath "%~dp0build_onefile" ^
  "%~dp0run_overlay.py"
