import sys
import threading
import traceback
from pathlib import Path
from datetime import datetime

# ── Crash logger ───────────────────────────────────────────────────────────────
# Must be set up BEFORE any other import so every error is captured.
# On Windows the tool runs as a subprocess with no visible console, so without
# this file ALL exceptions — including C-extension crashes — are lost.

_LOG = Path(__file__).parent / "crash.log"

def _write_log(header: str, text: str) -> None:
    try:
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(f"\n{'='*70}\n")
            f.write(f"{header}  [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
            f.write(f"{'='*70}\n")
            f.write(text + "\n")
    except Exception:
        pass

# Redirect stderr to both the log file and the real stderr
class _TeeStream:
    def __init__(self, real):
        self._real = real

    def write(self, s: str) -> None:
        try:
            self._real.write(s)
            self._real.flush()
        except Exception:
            pass
        if s.strip():
            _write_log("STDERR", s)

    def flush(self) -> None:
        try: self._real.flush()
        except Exception: pass

    def fileno(self):
        return self._real.fileno()

sys.stderr = _TeeStream(sys.stderr)

# Catch unhandled exceptions in the main thread
def _main_excepthook(exc_type, exc_value, exc_tb):
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _write_log("UNCAUGHT EXCEPTION (main thread)", text)
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _main_excepthook

# Catch unhandled exceptions in any background thread
def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    text = "".join(traceback.format_exception(
        args.exc_type, args.exc_value, args.exc_traceback))
    _write_log(f"UNCAUGHT EXCEPTION (thread: {args.thread})", text)

threading.excepthook = _thread_excepthook

# ── Normal startup ─────────────────────────────────────────────────────────────

_write_log("STARTUP", f"Python {sys.version}\nCWD: {Path.cwd()}")

# Tool-local imports (core/, ui/)
sys.path.insert(0, str(Path(__file__).parent))
# Shared imports (common/)
sys.path.insert(0, str(Path(__file__).parent.parent))

import customtkinter as ctk
from ui.audio_window import AudioWindow

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

if __name__ == "__main__":
    try:
        app = AudioWindow()
        app.mainloop()
    except Exception:
        _write_log("FATAL — mainloop crashed", traceback.format_exc())
        raise
