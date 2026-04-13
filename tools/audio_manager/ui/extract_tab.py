"""
Extract Tab — pull audio track out of any video file.

Supported input: MP4, MKV, AVI, MOV, WMV, FLV, WebM, and more (via ffmpeg).
The output format and quality preset are the same as in the Convert tab.
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from common.ui.widgets import SectionLabel, Separator, StatusBar
from core.audio_engine import AudioEngine
from core.formats import AUDIO_FORMATS, PRESETS, VIDEO_EXTS
from .widgets import MediaFilePicker


class ExtractTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, ffmpeg_ok: bool, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine    = engine
        self._ffmpeg_ok = ffmpeg_ok
        self._out_dir: Path | None = None
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        if not self._ffmpeg_ok:
            ctk.CTkLabel(
                self,
                text="⚠  ffmpeg non trovato.\n\n"
                     "Soluzione più semplice (nessuna installazione di sistema):\n\n"
                     "    pip install imageio-ffmpeg\n\n"
                     "Poi riavvia Multimedia Master.\n\n"
                     "In alternativa puoi installare ffmpeg nel sistema:\n"
                     "  • macOS:   brew install ffmpeg\n"
                     "  • Linux:   sudo apt install ffmpeg",
                font=ctk.CTkFont(size=12),
                text_color="#f44336",
                justify="left",
            ).grid(row=0, column=0, padx=40, pady=40, sticky="nw")
            return

        # File picker
        self._picker = MediaFilePicker(
            self, label="File video",
            exts=VIDEO_EXTS,
            on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew",
                          padx=12, pady=(12, 0))

        # Options panel
        opts = ctk.CTkFrame(self, fg_color=("#111", "#111"), corner_radius=10)
        opts.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 0))
        opts.grid_columnconfigure(1, weight=1)

        # Left column
        left = ctk.CTkFrame(opts, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 24), pady=12)
        left.grid_columnconfigure(0, weight=1)

        SectionLabel(left, "Formato output").pack(fill="x", pady=(0, 4))
        self._fmt_var = ctk.StringVar(value="mp3")
        ctk.CTkOptionMenu(left, variable=self._fmt_var,
                          values=list(AUDIO_FORMATS.keys()),
                          command=self._on_fmt_change,
                          dynamic_resizing=False).pack(fill="x")

        SectionLabel(left, "Preset qualità").pack(fill="x", pady=(12, 4))
        self._preset_var = ctk.StringVar(value="music")
        for key, info in PRESETS.items():
            if key == "custom":
                continue
            ctk.CTkRadioButton(
                left, text=info.label,
                variable=self._preset_var, value=key,
                command=self._on_preset_change,
            ).pack(anchor="w", pady=1)
        ctk.CTkRadioButton(
            left, text="Personalizzato",
            variable=self._preset_var, value="custom",
            command=self._on_preset_change,
        ).pack(anchor="w", pady=1)

        # Right column — custom bitrate (hidden unless custom)
        self._right = ctk.CTkFrame(opts, fg_color="transparent")
        self._right.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=12)
        self._right.grid_columnconfigure(0, weight=1)

        self._bitrate_lbl = ctk.CTkLabel(
            self._right, text="Bitrate: 320 kbps",
            anchor="w", font=ctk.CTkFont(size=11, weight="bold"))
        self._bitrate_lbl.pack(fill="x")
        self._bitrate_slider = ctk.CTkSlider(
            self._right, from_=32, to=320, number_of_steps=29,
            command=lambda v: self._bitrate_lbl.configure(
                text=f"Bitrate: {int(v)} kbps"))
        self._bitrate_slider.set(320)
        self._bitrate_slider.pack(fill="x", pady=(2, 8))

        SectionLabel(self._right, "Sample rate").pack(fill="x", pady=(4, 2))
        self._sr_var = ctk.StringVar(value="Originale")
        ctk.CTkOptionMenu(
            self._right, variable=self._sr_var,
            values=["Originale", "44100 Hz", "48000 Hz"],
            dynamic_resizing=False).pack(fill="x")

        Separator(self._right).pack(pady=(12, 4))

        SectionLabel(self._right, "Cartella output").pack(fill="x", pady=(4, 2))
        self._dir_lbl = ctk.CTkLabel(
            self._right, text="(stessa cartella del video)",
            text_color="gray", font=ctk.CTkFont(size=10), anchor="w")
        self._dir_lbl.pack(fill="x")
        ctk.CTkButton(self._right, text="Scegli", height=28,
                      command=self._choose_dir).pack(fill="x", pady=(4, 0))

        # Bottom bar
        self._progress = ctk.CTkProgressBar(self, height=6, corner_radius=3)
        self._progress.set(0)
        self._progress.grid(row=2, column=0, sticky="ew",
                            padx=12, pady=(8, 0))

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 0))
        bot.grid_columnconfigure(0, weight=1)
        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")
        self._btn_run = ctk.CTkButton(
            bot, text="▶  Estrai audio",
            width=140, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._run)
        self._btn_run.grid(row=0, column=1, padx=(8, 0))

        self._on_preset_change()

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_file_change(self, path: Path | None) -> None:
        if hasattr(self, "_btn_run"):
            self._btn_run.configure(
                state="normal" if path else "disabled")

    def _on_preset_change(self, *_) -> None:
        if not hasattr(self, "_right"):
            return
        if self._preset_var.get() == "custom":
            self._right.grid()
        else:
            # Hide custom controls but keep layout space
            pass   # always visible for simplicity

    def _on_fmt_change(self, fmt: str) -> None:
        lossy = AUDIO_FORMATS.get(fmt, AUDIO_FORMATS["mp3"]).lossy
        self._bitrate_slider.configure(
            state="normal" if lossy else "disabled")

    def _choose_dir(self) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d:
            self._out_dir = Path(d)
            self._dir_lbl.configure(
                text=f"…/{Path(d).name}", text_color="white")

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        video = self._picker.get_path()
        if not video:
            return

        fmt    = self._fmt_var.get()
        key    = self._preset_var.get()
        preset = PRESETS[key]

        if key == "custom":
            bitrate = int(self._bitrate_slider.get())
            sr_str  = self._sr_var.get()
            sr      = int(sr_str.split()[0]) if sr_str != "Originale" else None
        else:
            bitrate = preset.bitrate
            sr      = preset.sample_rate

        out_dir = self._out_dir or video.parent
        ext     = AUDIO_FORMATS[fmt].ext
        output  = out_dir / (video.stem + ext)

        self._btn_run.configure(state="disabled")
        self._progress.set(0)
        self._status.busy("Estrazione in corso…")
        threading.Thread(
            target=self._worker, args=(video, output, fmt, bitrate, sr),
            daemon=True,
        ).start()

    def _worker(self, video, output, fmt, bitrate, sr) -> None:
        def _prog(p: float) -> None:
            self.after(0, self._progress.set, p)
            self.after(0, self._status.busy,
                       f"Estrazione… {int(p*100)}%")

        result = self._engine.extract_audio(video, output, fmt, bitrate, sr,
                                             progress_cb=_prog)
        if result.success:
            sz = result.file_size / (1024 * 1024)
            self.after(0, self._status.ok,
                       f"Estratto: {output.name}  ({sz:.1f} MB)")
            self.after(0, self._progress.set, 1.0)
        else:
            self.after(0, self._status.err, result.error)
        self.after(0, self._btn_run.configure, {"state": "normal"})
