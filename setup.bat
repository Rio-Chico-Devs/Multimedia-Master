@echo off
REM ---------------------------------------------------------------------------
REM Create a local virtual environment (venv) and install everything needed to
REM run AND build Multimedia Master. Run this once from the project root; re-run
REM whenever requirements change. build.bat auto-activates venv if it exists.
REM ---------------------------------------------------------------------------

setlocal

REM Prefer the Windows "py" launcher, fall back to "python".
set PY=python
where py >nul 2>nul && set PY=py

if not exist venv (
    echo Creating virtual environment in venv ...
    %PY% -m venv venv
    if errorlevel 1 (
        echo.
        echo ERROR: could not create the venv. Is Python 3 installed and on PATH?
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo.
echo Upgrading pip ...
python -m pip install --upgrade pip

echo.
echo Installing core dependencies (requirements.txt) ...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: core dependency install failed.
    exit /b 1
)

echo.
echo Installing optional features: OCR + offline translation + word de-gluing ...
pip install -r requirements-optional.txt
if errorlevel 1 (
    echo.
    echo WARNING: optional deps failed to install. The app still runs, but OCR
    echo and/or PDF translation may be disabled. You can re-run setup.bat later.
)

echo.
echo Installing PyInstaller (needed to build the .exe) ...
pip install pyinstaller

echo.
echo ===========================================================================
echo  Done. The virtual environment is ready in venv
echo    - Build the Windows exe:   build.bat
echo    - Run from source:         python launcher.py
echo    - Work in the venv now:    call venv\Scripts\activate.bat
echo ===========================================================================

endlocal
