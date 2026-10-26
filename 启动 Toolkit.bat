@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% "FFRS_Toolkit.py"
if errorlevel 1 pause
