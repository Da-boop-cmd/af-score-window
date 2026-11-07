@echo off
cd /d "%~dp0"
set "MPLCONFIGDIR=%~dp0data\.mpl"
"runtime\python\pythonw.exe" -m afscore.desktop --app-dir "%~dp0"
if errorlevel 1 pause
