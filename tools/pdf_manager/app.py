import sys
from pathlib import Path

# Tool-local imports (core/, ui/)
sys.path.insert(0, str(Path(__file__).parent))
# Shared imports (common/)
sys.path.insert(0, str(Path(__file__).parent.parent))

# Crash logging FIRST — on Windows the tool has no console, so without
# this every exception (incl. C-extension crashes) is silently lost.
from common.crashlog import install as _install_crashlog
from common.paths import crash_log_path
_install_crashlog(crash_log_path("pdf_manager"))

import customtkinter as ctk
from ui.pdf_window import PdfWindow

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

if __name__ == "__main__":
    app = PdfWindow()
    app.mainloop()
