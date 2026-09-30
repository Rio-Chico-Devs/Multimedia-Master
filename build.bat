@echo off
REM Build a Windows exe (see MultimediaMaster.spec for what each target is).
REM
REM   build.bat          full suite -> dist\MultimediaMaster\MultimediaMaster.exe
REM   build.bat pdf      PDF only   -> dist\PdfManager\PdfManager.exe
REM
REM Set MM_ONEFILE=1 beforehand to get a single self-contained .exe instead of
REM a folder (build-pdf.bat does this for you).
REM
REM Run this from the project root. If a venv exists (created by setup.bat)
REM it is activated automatically; otherwise the current Python environment is
REM used and must already have every package from requirements.txt installed.

setlocal

if "%~1"=="" (set MM_TARGET=all) else (set MM_TARGET=%~1)

if /i "%MM_TARGET%"=="all" (
    set APP_NAME=MultimediaMaster
    set APP_LABEL=Multimedia Master ^(full suite^)
) else if /i "%MM_TARGET%"=="pdf" (
    set APP_NAME=PdfManager
    set APP_LABEL=PDF Manager ^(standalone^)
) else (
    echo Unknown target "%MM_TARGET%" - use "build.bat" or "build.bat pdf".
    exit /b 1
)

REM Accept the same spellings the spec does, so the paths reported at the end
REM can never disagree with what was actually built.
set ONEFILE=0
if /i "%MM_ONEFILE%"=="1"    set ONEFILE=1
if /i "%MM_ONEFILE%"=="true" set ONEFILE=1
if /i "%MM_ONEFILE%"=="yes"  set ONEFILE=1
if /i "%MM_ONEFILE%"=="on"   set ONEFILE=1

if "%ONEFILE%"=="1" (
    set WORK_NAME=%APP_NAME%-onefile
    set MODE_LABEL=single file
) else (
    set WORK_NAME=%APP_NAME%
    set MODE_LABEL=folder
)

echo.
echo Building: %APP_LABEL% - %MODE_LABEL%
echo.

if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat

pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Dependency vulnerability scan (advisory, never blocks the build). Flags any
REM dependency with a known CVE so we can bump it in requirements*.txt before
REM shipping the exe. Skipped silently if pip-audit isn't installed.
pip show pip-audit >nul 2>nul
if not errorlevel 1 (
    echo.
    echo Running pip-audit on requirements ...
    pip-audit -r requirements.txt -r requirements-optional.txt
    if errorlevel 1 (
        echo.
        echo WARNING: pip-audit reported known vulnerabilities above. Consider
        echo          bumping the affected packages in requirements*.txt before
        echo          distributing this build.
        echo.
    )
)

REM Per-target, per-mode work folder, so no build ever reuses another's cached
REM analysis. All targets share one spec file, which would otherwise share one
REM workpath and silently mix their collected dependencies.
rmdir /s /q build\%WORK_NAME% 2>nul
if "%ONEFILE%"=="1" (
    del /q "dist\%APP_NAME%.exe" 2>nul
) else (
    rmdir /s /q dist\%APP_NAME% 2>nul
)

pyinstaller --workpath build\%WORK_NAME% MultimediaMaster.spec

if errorlevel 1 (
    echo.
    echo BUILD FAILED - see the PyInstaller output above.
    exit /b 1
)

if "%ONEFILE%"=="1" (
    if not exist "dist\%APP_NAME%.exe" (
        echo.
        echo BUILD FAILED - dist\%APP_NAME%.exe was not produced.
        exit /b 1
    )
    echo.
    echo ===========================================================================
    echo  Done: dist\%APP_NAME%.exe
    echo.
    echo  That single file IS the program. Copy it anywhere - desktop, USB stick -
    echo  and double-click it. Nothing else needs to go with it.
    echo.
    echo  Every launch takes a few seconds: the exe unpacks itself to a temporary
    echo  folder each time it starts. That is normal for a single-file build.
    echo ===========================================================================
    goto :done
)

if not exist "dist\%APP_NAME%\%APP_NAME%.exe" (
    echo.
    echo BUILD FAILED - dist\%APP_NAME%\%APP_NAME%.exe was not produced.
    exit /b 1
)

echo.
echo Build OK: dist\%APP_NAME%\%APP_NAME%.exe

for /f %%i in ('python -c "import sys; sys.path.insert(0, 'tools'); from common.version import __version__; print(__version__)"') do set VERSION=%%i

set ZIP_NAME=%APP_NAME%-%VERSION%-win64.zip
del "dist\%ZIP_NAME%" 2>nul
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%APP_NAME%\*' -DestinationPath 'dist\%ZIP_NAME%' -Force"

if errorlevel 1 (
    echo.
    echo ZIP step failed - distribute the dist\%APP_NAME% folder manually.
    exit /b 1
)

echo.
echo Distribution zip ready: dist\%ZIP_NAME%
echo Distribute the WHOLE folder or that zip - the exe alone will not run.

:done
endlocal
