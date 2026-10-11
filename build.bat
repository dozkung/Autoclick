@echo off
REM Build AutoClicker.exe (single file, no console window)
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :err

REM pynput picks its backend via dynamic import, so PyInstaller cannot see it.
REM Without these hidden imports the exe opens and closes silently.
python -m PyInstaller --noconfirm --onefile --noconsole --name AutoClicker ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  autoclicker.py || goto :err

echo.
echo Done: dist\AutoClicker.exe
pause
exit /b 0

:err
echo.
echo Build failed
pause
exit /b 1
