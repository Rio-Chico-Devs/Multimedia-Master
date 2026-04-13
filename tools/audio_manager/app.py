import sys
from pathlib import Path

# Tool-local imports (core/, ui/)
sys.path.insert(0, str(Path(__file__).parent))
# Shared imports (common/)
sys.path.insert(0, str(Path(__file__).parent.parent))

import customtkinter as ctk
from ui.audio_window import AudioWindow

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

if __name__ == "__main__":
    app = AudioWindow()
    app.mainloop()
