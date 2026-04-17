"""
Audio Manager main window.

Seven tabs:
  1. Converti  — batch format conversion + quality presets
  2. Estrai    — extract audio track from any video
  3. Pulisci   — batch voice cleaner: WAV → web-optimised MP3
  4. Migliora  — noise reduction + normalisation
  5. Modifica  — trim, EQ, volume, fade, speed, split + waveform
  6. Separa    — stem separation via demucs
  7. Metadati  — ID3 / Vorbis / MP4 tag editor + album art

Dependency check runs once at startup; DepStatus is forwarded to tabs
so they can self-disable and show install instructions gracefully.
"""
from __future__ import annotations

import customtkinter as ctk

from core.audio_engine import AudioEngine
from core.dependencies import check as check_deps, install_hint

from .convert_tab  import ConvertTab
from .extract_tab  import ExtractTab
from .clean_tab    import CleanTab
from .enhance_tab  import EnhanceTab
from .edit_tab     import EditTab
from .stems_tab    import StemsTab
from .metadata_tab import MetadataTab


class AudioWindow(ctk.CTk):
    """Root window for the Audio Manager tool."""

    def __init__(self):
        super().__init__()
        self.title("Audio Manager — Multimedia Master")
        self.geometry("960x700")
        self.minsize(820, 580)

        self._engine = AudioEngine()
        self._deps   = check_deps()

        self._build()
        self._warn_missing_deps()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 0))
        ctk.CTkLabel(
            header, text="🎵  Audio Manager",
            font=ctk.CTkFont(size=22, weight="bold"),
            anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            header, text="100% offline  ·  nessun cloud",
            text_color="#555", font=ctk.CTkFont(size=11),
            anchor="e",
        ).pack(side="right")

        # Tab view
        tabs = ctk.CTkTabview(self, corner_radius=10)
        tabs.pack(fill="both", expand=True, padx=16, pady=(10, 16))

        for name in ("Converti", "Estrai", "Pulisci", "Migliora",
                     "Modifica", "Separa", "Metadati"):
            tabs.add(name)

        ConvertTab(tabs.tab("Converti"),
                   engine=self._engine).pack(fill="both", expand=True)

        ExtractTab(tabs.tab("Estrai"),
                   engine=self._engine,
                   ffmpeg_ok=self._deps.ffmpeg).pack(fill="both", expand=True)

        CleanTab(tabs.tab("Pulisci"),
                 engine=self._engine).pack(fill="both", expand=True)

        EnhanceTab(tabs.tab("Migliora"),
                   engine=self._engine,
                   deps=self._deps).pack(fill="both", expand=True)

        EditTab(tabs.tab("Modifica"),
                engine=self._engine,
                deps=self._deps).pack(fill="both", expand=True)

        StemsTab(tabs.tab("Separa"),
                 engine=self._engine,
                 deps=self._deps).pack(fill="both", expand=True)

        MetadataTab(tabs.tab("Metadati"),
                    engine=self._engine,
                    deps=self._deps).pack(fill="both", expand=True)

    # ── Dependency warnings ────────────────────────────────────────────────

    def _warn_missing_deps(self) -> None:
        hint = install_hint(self._deps)
        if not hint:
            return
        # Status strip at bottom
        strip = ctk.CTkFrame(self, fg_color="#2a1a00", corner_radius=0)
        strip.pack(fill="x", side="bottom", before=self.winfo_children()[0])
        ctk.CTkLabel(
            strip,
            text=f"⚠  Dipendenze mancanti  ·  {hint.splitlines()[0]}",
            text_color="#ffaa00",
            font=ctk.CTkFont(size=10),
            anchor="w",
        ).pack(side="left", padx=12, pady=4)
        ctk.CTkButton(
            strip, text="✕", width=28, height=22,
            fg_color="transparent", hover_color="#3a2a00",
            command=strip.destroy,
        ).pack(side="right", padx=8)
