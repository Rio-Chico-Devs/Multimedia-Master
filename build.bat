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
echo Copy the whole dist\MultimediaMaster folder to distribute the app.
