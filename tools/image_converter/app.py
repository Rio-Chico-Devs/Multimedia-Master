import sys
from pathlib import Path

# Always resolve imports relative to this tool's directory
sys.path.insert(0, str(Path(__file__).parent))

import customtkinter as ctk
from ui.main_window import MainWindow

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
