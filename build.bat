@echo off
REM Build Multimedia Master into a standalone Windows exe (onedir build).
REM Run this from the project root, inside the venv that has every package
REM from requirements.txt installed.

pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

pyinstaller MultimediaMaster.spec

if errorlevel 1 (
    echo.
    echo BUILD FAILED — see the PyInstaller output above.
    exit /b 1
)

echo.
echo Build OK: dist\MultimediaMaster\MultimediaMaster.exe

for /f %%i in ('python -c "import sys; sys.path.insert(0, 'tools'); from common.version import __version__; print(__version__)"') do set VERSION=%%i

set ZIP_NAME=MultimediaMaster-%VERSION%-win64.zip
del "dist\%ZIP_NAME%" 2>nul
powershell -NoProfile -Command "Compress-Archive -Path 'dist\MultimediaMaster\*' -DestinationPath 'dist\%ZIP_NAME%' -Force"

if errorlevel 1 (
    echo.
    echo ZIP step failed — distribute the dist\MultimediaMaster folder manually.
    exit /b 1
)

echo.
echo Distribution zip ready: dist\%ZIP_NAME%
