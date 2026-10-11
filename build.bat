@echo off
REM Build dist\AutoClicker-<version>\AutoClicker.exe (onedir, no console) + dist\AutoClicker-<version>.zip
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :err

REM Version lives only in autoclicker/constants.py (APP_VERSION); read it so names always match.
set "VER="
for /f "delims=" %%v in ('python -c "from autoclicker.constants import APP_VERSION; print(APP_VERSION)"') do set "VER=%%v"
if not defined VER goto :err

REM Version resource (company/description/version) is regenerated from constants.py every build.
REM An exe with version info gets fewer Defender false positives than a bare one.
python tools\make_version_info.py build\version_info.txt || goto :err

REM --onedir (not --onefile): onefile unpacks itself to %%TEMP%% at every launch, which looks like a
REM   dropper to antivirus. A plain folder of files is flagged far less often.
REM --noupx: UPX-packed exes are flagged more; never pack even if UPX is installed.
REM --icon: exe icon in Explorer = Tk feather (same as the window title bar icon).
REM pynput picks its backend via dynamic import, so PyInstaller cannot see it.
REM Without these hidden imports the exe opens and closes silently.
python -m PyInstaller --noconfirm --onedir --noconsole --noupx --name AutoClicker ^
  --version-file build\version_info.txt ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  --icon assets\app.ico ^
  main.py || goto :err

REM Exe stays AutoClicker.exe (what USER_GUIDE tells users to open); only the folder carries the version.
if exist "dist\AutoClicker-%VER%" rmdir /s /q "dist\AutoClicker-%VER%"
move "dist\AutoClicker" "dist\AutoClicker-%VER%" >nul || goto :err

if exist "dist\AutoClicker-%VER%.zip" del /q "dist\AutoClicker-%VER%.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\AutoClicker-%VER%' -DestinationPath 'dist\AutoClicker-%VER%.zip'" || goto :err

echo.
echo Done: dist\AutoClicker-%VER%\AutoClicker.exe
echo       dist\AutoClicker-%VER%.zip
pause
exit /b 0

:err
echo.
echo Build failed
pause
exit /b 1
