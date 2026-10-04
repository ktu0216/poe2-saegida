@echo off
rem Release build: release\poe2-saegida-setup-<ver>.exe (installer) + release\poe2-saegida-<ver>-portable.zip
rem Needs Inno Setup 6 (ISCC.exe). Version comes from poe2_overlay\__init__.py
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pytest -q || exit /b 1
call "%~dp0build.bat" || exit /b 1
".venv\Scripts\python.exe" -c "import poe2_overlay; print(poe2_overlay.__version__)" > "%TEMP%\poe2-saegida-ver.txt" || exit /b 1
set /p VER=<"%TEMP%\poe2-saegida-ver.txt"
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (echo Inno Setup 6 not found & exit /b 1)
if not exist release mkdir release
"%ISCC%" /Q /DMyAppVersion=%VER% installer\poe2-saegida.iss || exit /b 1
if exist "release\poe2-saegida-%VER%-portable.zip" del "release\poe2-saegida-%VER%-portable.zip"
powershell -NoProfile -Command "Compress-Archive -Path dist\poe2-saegida -DestinationPath release\poe2-saegida-%VER%-portable.zip"
echo Built release %VER%:
dir /b release
