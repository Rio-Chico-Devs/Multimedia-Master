@echo off
REM Build the PDF Manager on its own (no launcher, no image/audio tools).
REM Output: dist\PdfManager\PdfManager.exe
REM
REM Thin wrapper - build.bat holds the one and only build procedure, so the
REM two products can never drift apart.

call "%~dp0build.bat" pdf %*
exit /b %errorlevel%
