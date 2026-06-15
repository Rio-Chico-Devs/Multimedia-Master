import sys
import traceback
from pathlib import Path

# ── Python path setup (must come before any tool or common imports) ──────────
sys.path.insert(0, str(Path(__file__).parent))        # tool-local (core/, ui/)
sys.path.insert(0, str(Path(__file__).parent.parent)) # shared (common/)

# ── Crash logging FIRST ───────────────────────────────────────────────────────
# On Windows the tool runs as a subprocess with no visible console, so without
# this every exception (incl. C-extension crashes) is silently lost.
from common.crashlog import install as _install_crashlog, log as _log
_LOG = Path(__file__).parent / "crash.log"
_install_crashlog(_LOG)

# ── Wire up audio manager's internal debug logger ─────────────────────────────
# edit_tab and other modules import `from core import logger` for checkpoints.
from core import logger as _logger
_logger.setup(_LOG)

import customtkinter as ctk
from ui.audio_window import AudioWindow

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

if __name__ == "__main__":
    try:
        app = AudioWindow()
        app.mainloop()
    except Exception:
        _log("FATAL — mainloop crashed", traceback.format_exc())
        raise
