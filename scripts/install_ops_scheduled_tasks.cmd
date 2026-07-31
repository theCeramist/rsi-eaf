@echo off
REM Double-click or: scripts\install_ops_scheduled_tasks.cmd
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_ops_scheduled_tasks.ps1" %*
exit /b %ERRORLEVEL%
