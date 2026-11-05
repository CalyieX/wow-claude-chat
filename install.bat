@echo off
rem One-click setup: installs wowclaude and puts the addon into your game folder.
cd /d "%~dp0"
py -3 -m pip install --user . || goto :err
py -3 -m wowclaude setup || goto :err
echo.
echo Done. Restart the game, then run start.bat while you play.
pause
exit /b 0
:err
echo.
echo Setup failed. Is Python 3.9+ installed (https://www.python.org/downloads/)?
pause
exit /b 1
