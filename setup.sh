#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Create a local virtual environment (venv) and install everything needed to
# run Multimedia Master from source on Linux/macOS. (Windows builds use
# setup.bat + build.bat.) Re-run whenever requirements change.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

if [ ! -d venv ]; then
    echo "Creating virtual environment in venv ..."
    "$PY" -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

echo "Upgrading pip ..."
python -m pip install --upgrade pip

echo "Installing core dependencies (requirements.txt) ..."
pip install -r requirements.txt

echo "Installing optional features: OCR + offline translation + word de-gluing ..."
if ! pip install -r requirements-optional.txt; then
    echo "WARNING: optional deps failed; OCR/translation may be disabled."
fi

echo
echo "Done. Activate with:  source venv/bin/activate"
echo "Run from source with: python launcher.py"
