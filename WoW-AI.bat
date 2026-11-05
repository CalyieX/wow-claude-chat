@echo off
rem Double-click this. It installs what is missing, starts everything and starts with Windows.
cd /d "%~dp0"
py -3 --version >nul 2>&1 || (
  echo Python is missing - installing it now ...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python is installed. Close this window and double-click WoW-AI.bat again.
  pause
  exit /b 0
)
py -3 -m pip install --user --quiet . || (echo Install failed - check your internet connection. & pause & exit /b 1)
rem start with Windows (a shortcut in the Startup folder; delete it to stop that)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\WoW-AI.lnk');$s.TargetPath='%~dp0WoW-AI.bat';$s.WorkingDirectory='%~dp0';$s.WindowStyle=7;$s.Save()" >nul 2>&1
py -3 -m wowclaude go
pause
