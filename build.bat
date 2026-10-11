@echo off
REM Build AutoClicker-<version>.exe (single file, no console window)
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :err

REM Version lives only in autoclicker/constants.py (APP_VERSION); read it so the exe name always matches.
set "VER="
for /f "delims=" %%v in ('python -c "from autoclicker.constants import APP_VERSION; print(APP_VERSION)"') do set "VER=%%v"
if not defined VER goto :err

REM --icon: exe icon in Explorer = Tk feather (same as the window title bar icon).
REM pynput picks its backend via dynamic import, so PyInstaller cannot see it.
REM Without these hidden imports the exe opens and closes silently.
python -m PyInstaller --noconfirm --onefile --noconsole --name AutoClicker-%VER% ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  --icon assets\app.ico ^
  main.py || goto :err

echo.
echo Done: dist\AutoClicker-%VER%.exe
pause
exit /b 0

:err
echo.
echo Build failed
pause
exit /b 1
