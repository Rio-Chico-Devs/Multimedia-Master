# Tesseract OCR — vendoring for self-contained builds

This folder is **not for end users**. It's a one-time step for whoever
builds the distributable `.exe` (via `pyinstaller MultimediaMaster.spec`),
so that customers never have to install Tesseract OCR themselves — the OCR
and "Traduci" (scanned-PDF) features in PDF Manager just work out of the box
on whatever PC the app is installed on.

## What to do (once, on the build machine)

1. Install Tesseract OCR normally on the build machine using the official
   Windows installer:
   https://github.com/UB-Mannheim/tesseract/wiki

   Keep "Add to PATH" checked, and tick any additional languages you want
   bundled in the final app (at least English; add Italian if you'll ship
   to Italian users — both are needed for an en↔it translation pair).

2. Copy the **entire contents** of the installed folder into this directory,
   so it ends up looking like:

   ```
   vendor/tesseract/tesseract.exe
   vendor/tesseract/*.dll
   vendor/tesseract/tessdata/eng.traineddata
   vendor/tesseract/tessdata/ita.traineddata
   ...
   ```

   The installed folder is normally:
   `C:\Program Files\Tesseract-OCR\`

3. Build as usual:

   ```
   pyinstaller MultimediaMaster.spec
   ```

`dist/MultimediaMaster/` now contains its own private copy of Tesseract.
Zip that whole folder (or wrap it with an installer) and ship it — no
separate Tesseract installation is needed on the target PC.

## If you skip this step

The build still succeeds. OCR-dependent features (searchable-PDF export,
translating scanned pages) will require Tesseract to be installed
separately on whatever PC runs the app — the same as running from source
today.

## Why the binaries aren't committed to git

Tesseract's binaries + per-language data are tens of MB and are acquired
per-build-machine, not part of the source tree — `.gitignore` excludes
everything in this folder except this README.
