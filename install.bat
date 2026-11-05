@echo off
rem One-click setup: installs wowclaude and puts the addon into your game folder.
cd /d "%~dp0"
py -3 --version >nul 2>&1 || goto :nopython
py -3 -m pip install --user . || goto :pipfail
py -3 -m wowclaude setup || goto :setupfail
echo.
echo Done. Restart the game completely, then run start.bat while you play.
pause
exit /b 0
:nopython
echo.
echo Python 3.9+ was not found. Install it from https://www.python.org/downloads/ (tick "Add to PATH"), then run this again.
pause
exit /b 1
:pipfail
echo.
echo Installing the program failed (see the message above). Check your internet connection and run this again.
pause
exit /b 1
:setupfail
echo.
echo The addon could not be installed (see the message above). If the game folder was not found, run:
echo   py -3 -m wowclaude setup --root "C:\path\to\World of Warcraft\_forever_"
pause
exit /b 1
