@echo off
rem Release build: release\poe2-overlay-setup-<ver>.exe (installer) + release\poe2-overlay-<ver>-portable.zip
rem Needs Inno Setup 6 (ISCC.exe). Version comes from poe2_overlay\__init__.py
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pytest -q || exit /b 1
call build.bat || exit /b 1
for /f "delims=" %%v in ('".venv\Scripts\python.exe" -c "import poe2_overlay; print(poe2_overlay.__version__)"') do set VER=%%v
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (echo Inno Setup 6 not found & exit /b 1)
if not exist release mkdir release
"%ISCC%" /Q /DMyAppVersion=%VER% installer\poe2-overlay.iss || exit /b 1
if exist "release\poe2-overlay-%VER%-portable.zip" del "release\poe2-overlay-%VER%-portable.zip"
powershell -NoProfile -Command "Compress-Archive -Path dist\poe2-overlay -DestinationPath release\poe2-overlay-%VER%-portable.zip"
echo Built release %VER%:
dir /b release
