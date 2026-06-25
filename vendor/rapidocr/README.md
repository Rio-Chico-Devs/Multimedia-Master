# RapidOCR "latin" model — vendoring for accented-language accuracy

This folder is **not for end users**. It's an optional, one-time step for
whoever builds the distributable `.exe` (via `pyinstaller
MultimediaMaster.spec`), to improve OCR accuracy for Italian, French,
German, Spanish and other accented Latin-script languages.

## Do you need this at all?

Probably not to ship a working build — `pip install rapidocr-onnxruntime`
already bundles a Chinese+English recognition model **inside its own pip
wheel**, and `MultimediaMaster.spec` collects it automatically. No download,
no separate installer, nothing outside the app: that alone gives you a
fully self-contained OCR feature out of the box.

The catch: that stock model is tuned for Chinese + English, so it can
misread accented letters (à, è, ì, ò, ù, ç, ñ, ü...) common in Italian,
French, German and Spanish. If your scanned documents are mostly in those
languages and accuracy on accents matters, do the steps below once.

## What to do (once, on the build machine)

1. Download RapidOCR's official ONNX "latin" detection/recognition models
   (pre-converted to `.onnx`, ready to use — no PaddlePaddle install
   needed) from the project's own model list:
   https://rapidai.github.io/RapidOCRDocs/main/model_list/
   (or the GitHub releases page: https://github.com/RapidAI/RapidOCR/releases)

2. Place the files in this folder, named exactly:

   ```
   vendor/rapidocr/rec.onnx     # the "latin" recognition model
   vendor/rapidocr/keys.txt     # its matching character dictionary
   vendor/rapidocr/det.onnx     # optional — detection model (language-agnostic;
                                 #   the stock bundled one already works fine)
   vendor/rapidocr/cls.onnx     # optional — text-orientation classifier
   ```

3. Build as usual:

   ```
   pyinstaller MultimediaMaster.spec
   ```

`tools/common/ocr_engine.py` picks up whichever of these files exist and
uses them instead of the stock model — entirely from local disk, no network
access at any point, in dev mode or in the built `.exe`.

## If you skip this step

The build still succeeds and OCR still works (English text especially) —
it just uses RapidOCR's bundled Chinese+English model, which may misread
accented characters in other Latin-script languages.

## Why the model files aren't committed to git

They're tens of MB and acquired per-build-machine, not part of the source
tree — `.gitignore` excludes everything in this folder except this README.
