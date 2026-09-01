@echo off
setlocal
cd /d "%~dp0.."
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Windows companion is not installed yet.
  echo Run install_windows.ps1 from PowerShell first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0desktop_agent.py"
