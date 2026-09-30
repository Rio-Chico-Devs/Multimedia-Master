@echo off
REM Build the PDF Manager as ONE self-contained .exe.
REM
REM Output: dist\PdfManager.exe - a single file. Copy it onto a desktop, a USB
REM stick, anywhere, and double-click it. Nothing has to travel with it.
REM
REM The trade-off: that one file unpacks its whole payload to a temporary
REM folder on every launch, so starting it takes a few seconds. If you would
REM rather have instant startup and do not mind shipping a folder, run
REM "build.bat pdf" instead.
REM
REM Thin wrapper - build.bat holds the one and only build procedure, so the
REM products can never drift apart.

setlocal
set MM_ONEFILE=1
call "%~dp0build.bat" pdf %*
exit /b %errorlevel%
