@echo off
cd /d "%~dp0"
set "MPLCONFIGDIR=%~dp0data\.mpl"
echo Starting af-score (debug mode, errors stay in this window) ...
af-score.exe
if errorlevel 1 pause
