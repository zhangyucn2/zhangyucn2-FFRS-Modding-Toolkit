@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo FFRS Sprite ^<^-> PSD Tool v1.1 - Windows EXE Build
echo ============================================================
echo.

set "PYTHON="
if exist "C:\Python314\python.exe" set "PYTHON=C:\Python314\python.exe"
if not defined PYTHON (
    where py >nul 2>nul
    if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
    echo ERROR: Python was not found.
    echo Install Python 3.14.x, or edit this BAT and set PYTHON manually.
    exit /b 1
)

echo Using: %PYTHON%
echo.

if exist ".build_venv" (
    echo [1/4] Reusing .build_venv ...
) else (
    echo [1/4] Creating .build_venv ...
    %PYTHON% -m venv .build_venv
    if errorlevel 1 goto :fail
)

call ".build_venv\Scripts\activate.bat"
if errorlevel 1 goto :fail

echo [2/4] Installing build dependencies ...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

echo [3/4] Cleaning previous PyInstaller output ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "FFRS_SpritePSD_Tool_v1.1.spec" del /q "FFRS_SpritePSD_Tool_v1.1.spec"

echo [4/4] Building one-file Windows EXE ...
python -m PyInstaller --noconfirm --clean FFRS_SpritePSD_Tool_v1_1.spec
if errorlevel 1 goto :fail

copy /Y README_FFRS_SpritePSD_Tool_v1.1.txt dist\ >nul
copy /Y EXE_RELEASE_README.txt dist\ >nul

echo.
echo ============================================================
echo BUILD COMPLETE
echo ============================================================
echo EXE:
echo %CD%\dist\FFRS_SpritePSD_Tool_v1.1.exe
echo.
echo End users do not need Python or any Python packages.
echo ============================================================
exit /b 0

:fail
echo.
echo ============================================================
echo BUILD FAILED
echo ============================================================
exit /b 1
