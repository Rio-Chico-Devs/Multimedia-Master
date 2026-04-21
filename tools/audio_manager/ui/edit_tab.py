"""
Edit Tab — audio editor with playback, precise time inputs and batch actions.

Features:
  • Waveform with draggable trim markers + moving playhead
  • Playback (play/stop) via simpleaudio; cursor follows the audio
  • Precise mm:ss.ss time inputs two-way synced with markers
  • Immediate actions: split at cursor / into N parts, mute region
  • Chain-and-export: trim ⇢ EQ ⇢ volume/fade ⇢ speed ⇢ format
  • EQ now works on MP3/AAC (decoded to temp WAV internally)
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import customtkinter as ctk

from common.ui.widgets import SectionLabel, StatusBar
from core.audio_engine import AudioEngine, AudioInfo, safe_tempfile, VOICE_EFFECTS
from core.dependencies import DepStatus
from core.formats import AUDIO_EXTS, AUDIO_FORMATS
from .widgets import MediaFilePicker, WaveformCanvas


# ── Time helpers ───────────────────────────────────────────────────────────────

def _fmt_time(ms: int) -> str:
    """Format ms as 'm:ss.ss'."""
    ms = max(0, int(ms))
    m  = ms // 60000
    s  = (ms % 60000) / 1000
    return f"{m}:{s:05.2f}"


def _parse_time(text: str, max_ms: int) -> int | None:
    """Parse 'm:ss.ss' or plain seconds into ms (clamped to [0, max_ms])."""
    text = text.strip()
    if not text:
        return None
    try:
        if ":" in text:
            parts = text.split(":")
            if len(parts) == 2:
                m, s = parts
                ms = (int(m) * 60 + float(s)) * 1000
            elif len(parts) == 3:
                h, m, s = parts
                ms = (int(h) * 3600 + int(m) * 60 + float(s)) * 1000
            else:
                return None
        else:
            ms = float(text) * 1000
    except ValueError:
        return None
    return int(max(0, min(ms, max_ms)))


# ── Edit tab ───────────────────────────────────────────────────────────────────

class EditTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, deps: DepStatus, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine = engine
        self._deps   = deps
        self._info:             AudioInfo | None = None
        self._play_obj                           = None
        self._playing:          bool             = False
        self._play_gen:         int              = 0
        self._play_start_time:  float            = 0.0
        self._play_start_ms:    int              = 0
        self._after_id:         str | None       = None
        self._preview_timer:    str | None       = None
        self._previewing:       bool             = False
        self._voice_effect_var: ctk.StringVar    = ctk.StringVar(value="none")
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # Row 0 — file picker
        self._picker = MediaFilePicker(
            self, label="File audio",
            exts=AUDIO_EXTS,
            on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 0))

        # Row 1 — waveform
        wf_frame = ctk.CTkFrame(self, fg_color=("#0d0d0d", "#0d0d0d"),
                                 corner_radius=8)
        wf_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 0))
        wf_frame.grid_columnconfigure(0, weight=1)

        self._wf = WaveformCanvas(
            wf_frame, height=120,
            on_trim_change=self._on_trim_drag,
            on_cursor_change=self._on_cursor_click,
        )
        self._wf.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self._wf_info = ctk.CTkLabel(
            wf_frame,
            text="Apri un file audio per visualizzare la forma d'onda",
            text_color="#555", font=ctk.CTkFont(size=10))
        self._wf_info.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 4))

        # Row 2 — playback controls
        pb = ctk.CTkFrame(self, fg_color=("#111", "#111"), corner_radius=8)
        pb.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 0))
        for i in range(7):
            pb.grid_columnconfigure(i, weight=0)
        pb.grid_columnconfigure(6, weight=1)

        self._btn_play = ctk.CTkButton(
            pb, text="▶ Play", width=80, height=30, state="disabled",
            command=self._play)
        self._btn_play.grid(row=0, column=0, padx=(8, 4), pady=8)
        self._btn_stop = ctk.CTkButton(
            pb, text="■ Stop", width=80, height=30, state="disabled",
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            command=self._stop)
        self._btn_stop.grid(row=0, column=1, padx=4, pady=8)
        ctk.CTkButton(
            pb, text="⏮ Inizio", width=80, height=30,
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            command=lambda: self._seek_cursor(0),
        ).grid(row=0, column=2, padx=4, pady=8)
        ctk.CTkButton(
            pb, text="⏭ Fine", width=80, height=30,
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            command=lambda: self._seek_cursor(
                int(self._info.duration_s * 1000) if self._info else 0),
        ).grid(row=0, column=3, padx=4, pady=8)

        ctk.CTkLabel(pb, text="Cursore:",
                     font=ctk.CTkFont(size=11),
                     text_color="#888").grid(row=0, column=4, padx=(16, 4))
        self._cursor_lbl = ctk.CTkLabel(
            pb, text="0:00.00",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff")
        self._cursor_lbl.grid(row=0, column=5, padx=(0, 8))

        self._dur_lbl = ctk.CTkLabel(
            pb, text="— / —",
            font=ctk.CTkFont(size=10), text_color="#666", anchor="e")
        self._dur_lbl.grid(row=0, column=6, sticky="e", padx=(0, 12))

        # Row 3 — preview bar
        pv = ctk.CTkFrame(self, fg_color=("#0e1a2a", "#0e1a2a"), corner_radius=8)
        pv.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 0))
        for i in range(4):
            pv.grid_columnconfigure(i, weight=0)
        pv.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(
            pv, text="🎧  Anteprima effetti",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#6ab0e0",
        ).grid(row=0, column=0, padx=(12, 8), pady=6)

        self._btn_preview = ctk.CTkButton(
            pv, text="▶ Genera", width=90, height=28, state="disabled",
            command=self._play_preview)
        self._btn_preview.grid(row=0, column=1, padx=4, pady=6)

        self._btn_stop_preview = ctk.CTkButton(
            pv, text="■ Stop", width=80, height=28, state="disabled",
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            command=self._stop_preview)
        self._btn_stop_preview.grid(row=0, column=2, padx=4, pady=6)

        ctk.CTkLabel(
            pv, text="clip 6 s dalla posizione del cursore",
            text_color="#445", font=ctk.CTkFont(size=10),
        ).grid(row=0, column=3, padx=(8, 0), pady=6)

        self._preview_status_lbl = ctk.CTkLabel(
            pv, text="—", text_color="#555",
            font=ctk.CTkFont(size=10), anchor="e")
        self._preview_status_lbl.grid(row=0, column=4, sticky="e", padx=(0, 12))

        # Row 4 — scrollable sections
        self._sf = ctk.CTkScrollableFrame(
            self, fg_color=("#0a0a0a", "#0a0a0a"), corner_radius=10)
        self._sf.grid(row=4, column=0, sticky="nsew", padx=12, pady=(8, 0))
        self._sf.grid_columnconfigure(0, weight=1)

        self._build_selection_section()
        self._build_split_section()
        self._build_volume_section()
        self._build_eq_section()
        self._build_speed_section()
        self._build_voice_effects_section()
        self._build_output_section()

        # Row 5 — bottom bar
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=5, column=0, sticky="ew", padx=12, pady=(6, 0))
        bot.grid_columnconfigure(0, weight=1)
        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")
        self._btn_apply = ctk.CTkButton(
            bot, text="💾  Applica ed Esporta",
            width=200, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._run)
        self._btn_apply.grid(row=0, column=1, padx=(8, 0))

    # ── Card helper ────────────────────────────────────────────────────────

    def _card(self, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self._sf, fg_color=("#141414", "#141414"),
                            corner_radius=8)
        card.pack(fill="x", padx=4, pady=4)
        card.grid_columnconfigure(0, weight=1)
        SectionLabel(card, title).grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 4))
        return card

    # ── Selection (trim OR mute) section ──────────────────────────────────

    def _build_selection_section(self) -> None:
        card = self._card("✂  Selezione  (trascina i marcatori o digita i tempi)")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(3, weight=1)

        self._sel_action_var = ctk.StringVar(value="none")
        ctk.CTkRadioButton(body, text="Nessuna azione",
                           variable=self._sel_action_var, value="none"
                           ).grid(row=0, column=0, columnspan=4,
                                  sticky="w", pady=(0, 2))
        ctk.CTkRadioButton(body, text="Taglia (mantieni solo la selezione)",
                           variable=self._sel_action_var, value="trim"
                           ).grid(row=1, column=0, columnspan=4,
                                  sticky="w", pady=2)
        ctk.CTkRadioButton(body, text="Silenzia la selezione (stessa durata)",
                           variable=self._sel_action_var, value="mute"
                           ).grid(row=2, column=0, columnspan=4,
                                  sticky="w", pady=2)

        # Start time
        ctk.CTkLabel(body, text="Inizio:", width=60, anchor="w",
                     font=ctk.CTkFont(size=11)
                     ).grid(row=3, column=0, sticky="w", pady=(10, 2))
        self._start_entry = ctk.CTkEntry(body, placeholder_text="0:00.00",
                                          width=90)
        self._start_entry.grid(row=3, column=1, sticky="w", pady=(10, 2))
        self._start_entry.bind("<Return>",   lambda _: self._apply_time_entries())
        self._start_entry.bind("<FocusOut>", lambda _: self._apply_time_entries())
        ctk.CTkButton(body, text="⇦ al cursore", width=100, height=24,
                      fg_color="#2a2a2a", hover_color="#3a3a3a",
                      command=self._start_to_cursor,
                      ).grid(row=3, column=2, padx=(6, 0), pady=(10, 2))

        # End time
        ctk.CTkLabel(body, text="Fine:", width=60, anchor="w",
                     font=ctk.CTkFont(size=11)
                     ).grid(row=4, column=0, sticky="w", pady=2)
        self._end_entry = ctk.CTkEntry(body, placeholder_text="0:00.00",
                                        width=90)
        self._end_entry.grid(row=4, column=1, sticky="w", pady=2)
        self._end_entry.bind("<Return>",   lambda _: self._apply_time_entries())
        self._end_entry.bind("<FocusOut>", lambda _: self._apply_time_entries())
        ctk.CTkButton(body, text="⇦ al cursore", width=100, height=24,
                      fg_color="#2a2a2a", hover_color="#3a3a3a",
                      command=self._end_to_cursor,
                      ).grid(row=4, column=2, padx=(6, 0), pady=2)

        self._sel_dur_lbl = ctk.CTkLabel(
            body, text="Durata selezione: —",
            text_color="#888", font=ctk.CTkFont(size=10), anchor="w")
        self._sel_dur_lbl.grid(row=5, column=0, columnspan=4,
                               sticky="w", pady=(6, 0))

    # ── Split section ──────────────────────────────────────────────────────

    def _build_split_section(self) -> None:
        card = self._card("🔀  Dividi file  (azione immediata, crea più file)")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        body.grid_columnconfigure(3, weight=1)

        ctk.CTkButton(body, text="✂ Dividi al cursore",
                      width=170, height=30, command=self._split_at_cursor,
                      ).grid(row=0, column=0, padx=(0, 8), pady=(0, 4))
        ctk.CTkLabel(body, text="oppure",
                     text_color="#666", font=ctk.CTkFont(size=10)
                     ).grid(row=0, column=1, padx=8)
        ctk.CTkLabel(body, text="in",
                     font=ctk.CTkFont(size=11)
                     ).grid(row=0, column=2, padx=(8, 4))
        self._nparts_entry = ctk.CTkEntry(body, width=50,
                                           placeholder_text="3")
        self._nparts_entry.insert(0, "3")
        self._nparts_entry.grid(row=0, column=3, sticky="w")
        ctk.CTkLabel(body, text="parti uguali",
                     font=ctk.CTkFont(size=11)
                     ).grid(row=0, column=4, padx=(4, 8))
        ctk.CTkButton(body, text="✂ Dividi",
                      width=100, height=30,
                      command=self._split_equal_parts,
                      ).grid(row=0, column=5)

        ctk.CTkLabel(body,
                     text="Output: <nome>_part01.<ext>, _part02.<ext>, …\n"
                          "nella stessa cartella del file originale.",
                     text_color="#666", font=ctk.CTkFont(size=10),
                     justify="left", anchor="w",
                     ).grid(row=1, column=0, columnspan=6,
                            sticky="w", pady=(8, 0))

    # ── Volume & Fade ──────────────────────────────────────────────────────

    def _build_volume_section(self) -> None:
        card = self._card("🔊  Volume & Fade")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        body.grid_columnconfigure(0, weight=1)

        self._gain_lbl = ctk.CTkLabel(body, text="Gain: 0 dB", anchor="w",
                                       font=ctk.CTkFont(size=11, weight="bold"))
        self._gain_lbl.pack(fill="x")
        self._gain_slider = ctk.CTkSlider(
            body, from_=-20, to=20, number_of_steps=40,
            command=lambda v: self._gain_lbl.configure(text=f"Gain: {v:+.0f} dB"))
        self._gain_slider.set(0)
        self._gain_slider.pack(fill="x", pady=(2, 10))

        self._fi_lbl = ctk.CTkLabel(body, text="Fade in: 0.0 s", anchor="w",
                                     font=ctk.CTkFont(size=11, weight="bold"))
        self._fi_lbl.pack(fill="x")
        self._fi_slider = ctk.CTkSlider(
            body, from_=0, to=10, number_of_steps=100,
            command=lambda v: self._fi_lbl.configure(text=f"Fade in: {v:.1f} s"))
        self._fi_slider.set(0)
        self._fi_slider.pack(fill="x", pady=(2, 10))

        self._fo_lbl = ctk.CTkLabel(body, text="Fade out: 0.0 s", anchor="w",
                                     font=ctk.CTkFont(size=11, weight="bold"))
        self._fo_lbl.pack(fill="x")
        self._fo_slider = ctk.CTkSlider(
            body, from_=0, to=10, number_of_steps=100,
            command=lambda v: self._fo_lbl.configure(text=f"Fade out: {v:.1f} s"))
        self._fo_slider.set(0)
        self._fo_slider.pack(fill="x", pady=(2, 0))

    # ── EQ ─────────────────────────────────────────────────────────────────

    def _build_eq_section(self) -> None:
        card = self._card("🎚  Equalizzatore 3 bande")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        body.grid_columnconfigure(0, weight=1)

        eq_ok = self._deps.soundfile and self._deps.scipy and self._deps.numpy
        if not eq_ok:
            ctk.CTkLabel(
                body,
                text="⚠  Richiede: pip install soundfile scipy numpy",
                text_color="#f44336", font=ctk.CTkFont(size=10),
            ).pack(anchor="w", pady=(0, 6))
        else:
            ctk.CTkLabel(
                body,
                text="Funziona anche su MP3/AAC (decodifica temporanea).",
                text_color="#666", font=ctk.CTkFont(size=10),
            ).pack(anchor="w", pady=(0, 6))

        state = "normal" if eq_ok else "disabled"
        self._eq_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(body, text="Abilita EQ", variable=self._eq_var,
                        state=state).pack(anchor="w", pady=(0, 8))

        for attr, label in [
            ("_bass",   "Bassi   (<250 Hz)"),
            ("_mid",    "Medi    (250–4 kHz)"),
            ("_treble", "Acuti   (>4 kHz)"),
        ]:
            lbl = ctk.CTkLabel(body, text=f"{label}: 0 dB",
                                anchor="w", font=ctk.CTkFont(size=10))
            lbl.pack(fill="x")
            slider = ctk.CTkSlider(
                body, from_=-12, to=12, number_of_steps=24, state=state,
                command=lambda v, l=lbl, n=label: l.configure(
                    text=f"{n}: {v:+.0f} dB"))
            slider.set(0)
            slider.pack(fill="x", pady=(2, 6))
            setattr(self, attr, slider)

    # ── Speed ──────────────────────────────────────────────────────────────

    def _build_speed_section(self) -> None:
        card = self._card("⏩  Velocità")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        body.grid_columnconfigure(0, weight=1)

        self._speed_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(body, text="Abilita cambio velocità",
                        variable=self._speed_var).pack(anchor="w", pady=(0, 6))
        self._speed_lbl = ctk.CTkLabel(
            body, text="Velocità: 1.00×", anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"))
        self._speed_lbl.pack(fill="x")
        self._speed_slider = ctk.CTkSlider(
            body, from_=0.5, to=2.0, number_of_steps=30,
            command=lambda v: self._speed_lbl.configure(
                text=f"Velocità: {v:.2f}×"))
        self._speed_slider.set(1.0)
        self._speed_slider.pack(fill="x", pady=(2, 0))

    # ── Voice effects ──────────────────────────────────────────────────

    def _build_voice_effects_section(self) -> None:
        card = self._card("🎭  Effetti voce speciali")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body,
            text="Applicato dopo tutti gli altri effetti. "
                 "Usa il pulsante Anteprima per testarlo prima di esportare.",
            text_color="#666", font=ctk.CTkFont(size=10), justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # Radio buttons in a 4-column grid
        btn_frame = ctk.CTkFrame(body, fg_color="transparent")
        btn_frame.pack(fill="x")
        for col in range(4):
            btn_frame.grid_columnconfigure(col, weight=1)

        effect_choices = [("none", "❌  Nessuno")] + [
            (k, v[0].split("  —")[0]) for k, v in VOICE_EFFECTS.items()
        ]
        for idx, (key, label) in enumerate(effect_choices):
            ctk.CTkRadioButton(
                btn_frame,
                text=label,
                variable=self._voice_effect_var,
                value=key,
                command=self._on_effect_change,
                font=ctk.CTkFont(size=11),
            ).grid(row=idx // 4, column=idx % 4,
                   sticky="w", padx=6, pady=3)

        self._effect_desc_lbl = ctk.CTkLabel(
            body, text="",
            text_color="#888", font=ctk.CTkFont(size=10),
            wraplength=520, justify="left", anchor="w")
        self._effect_desc_lbl.pack(fill="x", pady=(8, 0))

    def _on_effect_change(self) -> None:
        key = self._voice_effect_var.get()
        if key == "none" or key not in VOICE_EFFECTS:
            self._effect_desc_lbl.configure(text="")
        else:
            desc, _ = VOICE_EFFECTS[key]
            self._effect_desc_lbl.configure(text=desc)

    # ── Output ─────────────────────────────────────────────────────────────

    def _build_output_section(self) -> None:
        self._out_dir: Path | None = None
        card = self._card("💾  Output")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        body.grid_columnconfigure(1, weight=1)

        # Format
        ctk.CTkLabel(body, text="Formato:", width=70, anchor="w",
                     font=ctk.CTkFont(size=11)
                     ).grid(row=0, column=0, sticky="w", pady=2)
        self._out_fmt_var = ctk.StringVar(value="Stesso del file")
        ctk.CTkOptionMenu(
            body, variable=self._out_fmt_var,
            values=["Stesso del file"] + list(AUDIO_FORMATS.keys()),
            dynamic_resizing=False,
        ).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=2)

        # Suffix (empty = same name, overwrites source if same folder)
        ctk.CTkLabel(body, text="Suffisso:", width=70, anchor="w",
                     font=ctk.CTkFont(size=11)
                     ).grid(row=1, column=0, sticky="w", pady=2)
        self._suffix_entry = ctk.CTkEntry(
            body, placeholder_text="vuoto = stesso nome (sovrascrive)")
        self._suffix_entry.insert(0, "_modificato")
        self._suffix_entry.grid(row=1, column=1, columnspan=3, sticky="ew",
                                padx=(4, 0), pady=2)

        # Output folder
        ctk.CTkLabel(body, text="Cartella:", width=70, anchor="w",
                     font=ctk.CTkFont(size=11)
                     ).grid(row=2, column=0, sticky="w", pady=(8, 2))
        self._out_dir_lbl = ctk.CTkLabel(
            body, text="Stessa del file sorgente",
            anchor="w", text_color="gray",
            font=ctk.CTkFont(size=11))
        self._out_dir_lbl.grid(row=2, column=1, sticky="ew",
                               padx=(4, 0), pady=(8, 2))
        ctk.CTkButton(body, text="Sfoglia", width=72, height=28,
                      command=self._browse_out_dir,
                      ).grid(row=2, column=2, padx=(8, 0), pady=(8, 2))
        ctk.CTkButton(body, text="✕", width=30, height=28,
                      fg_color="#2a2a2a", hover_color="#3a3a3a",
                      command=self._clear_out_dir,
                      ).grid(row=2, column=3, padx=(4, 0), pady=(8, 2))

    def _browse_out_dir(self) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Scegli cartella di output")
        if d:
            self._out_dir = Path(d)
            self._out_dir_lbl.configure(text=str(self._out_dir),
                                        text_color="white")

    def _clear_out_dir(self) -> None:
        self._out_dir = None
        self._out_dir_lbl.configure(text="Stessa del file sorgente",
                                    text_color="gray")

    # ── File loaded ────────────────────────────────────────────────────────

    def _on_file_change(self, path: Path | None) -> None:
        self._stop()
        if not path:
            self._wf.clear()
            self._wf_info.configure(
                text="Apri un file audio per visualizzare la forma d'onda")
            self._info = None
            self._cursor_lbl.configure(text="0:00.00")
            self._dur_lbl.configure(text="— / —")
            self._start_entry.delete(0, "end")
            self._end_entry.delete(0, "end")
            self._sel_dur_lbl.configure(text="Durata selezione: —")
            if hasattr(self, "_btn_apply"):
                self._btn_apply.configure(state="disabled")
                self._btn_play.configure(state="disabled")
                self._btn_preview.configure(state="disabled")
                self._btn_stop_preview.configure(state="disabled")
                self._preview_status_lbl.configure(text="—", text_color="#555")
            return

        self._status.busy("Caricamento forma d'onda…")
        threading.Thread(
            target=self._load_waveform, args=(path,), daemon=True
        ).start()

    def _load_waveform(self, path: Path) -> None:
        info = self._engine.probe(path)
        self._info = info
        pos, neg  = self._engine.get_waveform_peaks(path, num_samples=900)
        dur_ms    = int(info.duration_s * 1000)

        def _apply():
            self._wf.load_peaks(pos, neg, dur_ms)
            mins  = int(info.duration_s // 60)
            secs  = info.duration_s % 60
            self._wf_info.configure(
                text=f"{info.format.upper()}  ·  "
                     f"{info.sample_rate} Hz  ·  "
                     f"{'Stereo' if info.channels == 2 else 'Mono'}  ·  "
                     f"{info.bitrate_kbps} kbps",
                text_color="#aaa")
            self._dur_lbl.configure(
                text=f"{_fmt_time(0)} / {_fmt_time(dur_ms)}")
            self._cursor_lbl.configure(text="0:00.00")
            self._start_entry.delete(0, "end")
            self._start_entry.insert(0, _fmt_time(0))
            self._end_entry.delete(0, "end")
            self._end_entry.insert(0, _fmt_time(dur_ms))
            self._update_sel_duration()
            self._btn_apply.configure(state="normal")
            self._btn_play.configure(state="normal")
            self._btn_preview.configure(state="normal")
            self._status.info(
                "Riproduci, seleziona con i marcatori o digita i tempi, "
                "poi premi 'Applica ed Esporta'")

        self.after(0, _apply)

    # ── Waveform ↔ time inputs sync ────────────────────────────────────────

    def _on_trim_drag(self, start_ms: int, end_ms: int) -> None:
        self._start_entry.delete(0, "end")
        self._start_entry.insert(0, _fmt_time(start_ms))
        self._end_entry.delete(0, "end")
        self._end_entry.insert(0, _fmt_time(end_ms))
        self._update_sel_duration()

    def _on_cursor_click(self, cur_ms: int) -> None:
        self._cursor_lbl.configure(text=_fmt_time(cur_ms))

    def _apply_time_entries(self) -> None:
        if not self._info:
            return
        dur = int(self._info.duration_s * 1000)
        s = _parse_time(self._start_entry.get(), dur)
        e = _parse_time(self._end_entry.get(),   dur)
        if s is None or e is None or s >= e:
            return
        self._wf.set_trim_range(s, e)
        self._start_entry.delete(0, "end")
        self._start_entry.insert(0, _fmt_time(s))
        self._end_entry.delete(0, "end")
        self._end_entry.insert(0, _fmt_time(e))
        self._update_sel_duration()

    def _update_sel_duration(self) -> None:
        s, e = self._wf.get_trim_range()
        self._sel_dur_lbl.configure(
            text=f"Durata selezione: {_fmt_time(e - s)}")

    def _start_to_cursor(self) -> None:
        if not self._info:
            return
        cur = self._wf.get_cursor()
        _, e = self._wf.get_trim_range()
        if cur >= e:
            return
        self._wf.set_trim_range(cur, e)
        self._on_trim_drag(cur, e)

    def _end_to_cursor(self) -> None:
        if not self._info:
            return
        cur = self._wf.get_cursor()
        s, _ = self._wf.get_trim_range()
        if cur <= s:
            return
        self._wf.set_trim_range(s, cur)
        self._on_trim_drag(s, cur)

    def _seek_cursor(self, ms: int) -> None:
        if not self._info:
            return
        self._wf.set_cursor(ms)
        self._cursor_lbl.configure(text=_fmt_time(ms))

    # ── Playback ───────────────────────────────────────────────────────────
    # Uses sounddevice (PortAudio) instead of simpleaudio.
    # simpleaudio calls WinMM directly and crashes when stop()+play()
    # happen in rapid succession — e.g. slider move while audio is playing.

    @staticmethod
    def _sd_stop() -> None:
        """Stop all sounddevice streams (safe to call even if nothing plays)."""
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def _play(self) -> None:
        if not self._info:
            return
        if self._previewing:
            self._stop_preview()
        if self._playing:
            self._stop()
        path = self._picker.get_path()
        if not path:
            return
        dur_ms   = int(self._info.duration_s * 1000)
        start_ms = self._wf.get_cursor()
        if start_ms >= dur_ms - 200:   # at (or near) end → restart
            start_ms = 0
            self._seek_cursor(0)
        self._play_gen += 1
        gen = self._play_gen
        self._playing = True
        self._play_start_time = time.time()
        self._play_start_ms   = start_ms
        self._btn_play.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        threading.Thread(
            target=self._play_worker, args=(path, gen), daemon=True
        ).start()
        self._tick_playhead()

    def _play_worker(self, path: Path, gen: int) -> None:
        import wave, subprocess as sp
        from core import logger
        tmp: Path | None = None
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            self.after(0, self._status.err,
                       "Installa sounddevice: pip install sounddevice")
            self.after(0, lambda: self._stop_playback_ui(gen))
            return

        try:
            logger.log("PLAY_WORKER start", str(path))
            tmp = safe_tempfile(suffix=".wav")
            proc = sp.run(
                [self._engine._ffmpeg, "-y", "-i", str(path),
                 "-acodec", "pcm_s16le", "-ar", "44100", str(tmp)],
                stdout=sp.DEVNULL, stderr=sp.PIPE,
                encoding="utf-8", errors="replace",
            )
            logger.log("PLAY_WORKER ffmpeg done", f"rc={proc.returncode}")
            if proc.returncode != 0 or tmp.stat().st_size == 0:
                err = (proc.stderr or "").strip().splitlines()
                self.after(0, self._status.err,
                           f"Decodifica: {err[-1] if err else 'ffmpeg error'}")
                self.after(0, lambda: self._stop_playback_ui(gen))
                return

            with wave.open(str(tmp)) as wf:
                frame_rate  = wf.getframerate()
                n_ch        = wf.getnchannels()
                n_frames    = wf.getnframes()
                start_frame = int(self._play_start_ms / 1000 * frame_rate)
                start_frame = min(start_frame, max(n_frames - 1, 0))
                wf.setpos(start_frame)
                raw = wf.readframes(n_frames - start_frame)

            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if n_ch > 1:
                audio = audio.reshape(-1, n_ch)

            logger.log("PLAY_WORKER sd.play", f"{n_ch}ch {frame_rate}Hz {len(audio)} frames")
            sd.play(audio, frame_rate)
            sd.wait()
            logger.log("PLAY_WORKER sd.wait done")
        except Exception as exc:
            logger.log("PLAY_WORKER exception", str(exc))
            self.after(0, self._status.err, str(exc))
        finally:
            if tmp:
                try: tmp.unlink(missing_ok=True)
                except Exception: pass
            self.after(0, lambda: self._stop_playback_ui(gen))

    def _tick_playhead(self) -> None:
        if not self._playing or not self._info:
            return
        elapsed_ms = int((time.time() - self._play_start_time) * 1000)
        dur_ms     = int(self._info.duration_s * 1000)
        cur        = min(self._play_start_ms + elapsed_ms, dur_ms)
        self._wf.set_cursor(cur)
        self._cursor_lbl.configure(text=_fmt_time(cur))
        if cur >= dur_ms:
            self._stop()
            return
        self._after_id = self.after(50, self._tick_playhead)

    def _stop(self) -> None:
        self._sd_stop()
        self._stop_playback_ui()

    def _stop_playback_ui(self, gen: int = -1) -> None:
        if gen >= 0 and gen != self._play_gen:
            return
        self._playing = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._btn_play.configure(
            state="normal" if self._info else "disabled")
        self._btn_stop.configure(state="disabled")

    # ── Preview (manual, dedicated section) ──────────────────────────────

    def _play_preview(self) -> None:
        """Capture UI values on main thread, then launch preview worker."""
        if not self._info:
            return
        if self._previewing:
            self._stop_preview()
        if self._playing:
            self._stop()
        path = self._picker.get_path()
        if not path or not self._engine._ffmpeg:
            return

        # Capture every slider/var HERE on the main thread — calling tkinter
        # widget methods from a background thread crashes Tcl/Tk on Windows.
        try:
            params = {
                "cur_ms":        self._wf.get_cursor(),
                "gain":          self._gain_slider.get(),
                "eq":            self._eq_var.get(),
                "bass":          self._bass.get(),
                "mid":           self._mid.get(),
                "treble":        self._treble.get(),
                "speed_enabled": self._speed_var.get(),
                "speed":         self._speed_slider.get(),
            }
        except Exception as exc:
            self._status.err(f"Lettura parametri: {exc}")
            return

        self._play_gen += 1
        gen = self._play_gen
        self._previewing = True
        self._btn_preview.configure(state="disabled")
        self._btn_stop_preview.configure(state="normal")
        self._preview_status_lbl.configure(text="Generazione…", text_color="#aaa")
        threading.Thread(target=self._preview_worker,
                         args=(path, gen, params), daemon=True).start()

    def _stop_preview(self) -> None:
        self._sd_stop()
        self._stop_preview_ui()

    def _stop_preview_ui(self, gen: int = -1) -> None:
        if gen >= 0 and gen != self._play_gen:
            return
        self._previewing = False
        self._btn_preview.configure(
            state="normal" if self._info else "disabled")
        self._btn_stop_preview.configure(state="disabled")
        self._preview_status_lbl.configure(text="—", text_color="#555")

    def _preview_worker(self, path: Path, gen: int, params: dict) -> None:
        """Build ffmpeg filter chain from pre-captured params, play 6-second clip."""
        import wave, subprocess as sp
        from core import logger
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            self.after(0, lambda: self._preview_status_lbl.configure(
                text="pip install sounddevice", text_color="#f44336"))
            self.after(0, lambda: self._stop_preview_ui(gen))
            return

        tmp: Path | None = None
        try:
            cur_s  = params["cur_ms"] / 1000.0
            clip_s = 6.0

            filters: list[str] = []
            gain = params["gain"]
            if gain != 0:
                filters.append(f"volume={gain:.1f}dB")
            if params["eq"]:
                bass, mid, treble = params["bass"], params["mid"], params["treble"]
                if bass   != 0: filters.append(f"bass=g={bass:.1f}")
                if treble != 0: filters.append(f"treble=g={treble:.1f}")
                if mid    != 0:
                    filters.append(
                        f"equalizer=f=1000:width_type=o:width=2:g={mid:.1f}")
            if params["speed_enabled"]:
                spd = params["speed"]
                if spd != 1.0:
                    if spd < 0.5:
                        filters += [f"atempo={spd*2:.3f}", "atempo=0.5"]
                    elif spd > 2.0:
                        filters += [f"atempo={spd/2:.3f}", "atempo=2.0"]
                    else:
                        filters.append(f"atempo={spd:.3f}")

            tmp = safe_tempfile(suffix=".wav")
            cmd = [self._engine._ffmpeg, "-y",
                   "-ss", str(cur_s), "-t", str(clip_s),
                   "-i",  str(path)]
            if filters:
                cmd += ["-af", ",".join(filters)]
            cmd += ["-ar", "44100", "-acodec", "pcm_s16le", str(tmp)]

            logger.log("PREVIEW ffmpeg start",
                       f"filters={filters} cur={cur_s:.1f}s")
            proc = sp.run(cmd, stdout=sp.DEVNULL, stderr=sp.PIPE,
                          encoding="utf-8", errors="replace")
            logger.log("PREVIEW ffmpeg done", f"rc={proc.returncode}")

            if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                lines = (proc.stderr or "").strip().splitlines()
                msg   = lines[-1] if lines else "ffmpeg ha fallito"
                self.after(0, lambda m=msg: self._preview_status_lbl.configure(
                    text=f"Errore: {m}", text_color="#f44336"))
                return

            with wave.open(str(tmp)) as wf:
                frame_rate = wf.getframerate()
                n_ch       = wf.getnchannels()
                raw        = wf.readframes(wf.getnframes())

            if gen != self._play_gen:
                return

            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if n_ch > 1:
                audio = audio.reshape(-1, n_ch)

            self.after(0, lambda: self._preview_status_lbl.configure(
                text="▶ in riproduzione", text_color="#4fa8e0"))

            logger.log("PREVIEW sd.play",
                       f"{n_ch}ch {frame_rate}Hz {len(audio)} frames")
            sd.play(audio, frame_rate)
            sd.wait()
            logger.log("PREVIEW sd.wait done")
        except Exception as exc:
            logger.log("PREVIEW exception", str(exc))
            self.after(0, lambda e=exc: self._preview_status_lbl.configure(
                text=f"Errore: {e}", text_color="#f44336"))
        finally:
            if tmp:
                try: tmp.unlink(missing_ok=True)
                except Exception: pass
            self.after(0, lambda: self._stop_preview_ui(gen))

    # ── Split actions (immediate) ─────────────────────────────────────────

    def _split_at_cursor(self) -> None:
        if not self._info:
            self._status.err("Apri un file audio.")
            return
        cur = self._wf.get_cursor()
        dur = int(self._info.duration_s * 1000)
        if cur <= 0 or cur >= dur:
            self._status.err("Posiziona il cursore dentro il file.")
            return
        path = self._picker.get_path()
        self._status.busy("Divisione in corso…")
        threading.Thread(
            target=self._split_worker, args=(path, [cur]), daemon=True
        ).start()

    def _split_equal_parts(self) -> None:
        if not self._info:
            self._status.err("Apri un file audio.")
            return
        try:
            n = int(self._nparts_entry.get().strip())
        except ValueError:
            self._status.err("Numero di parti non valido.")
            return
        if n < 2 or n > 50:
            self._status.err("Numero parti: 2–50.")
            return
        dur = int(self._info.duration_s * 1000)
        points = [int(dur * i / n) for i in range(1, n)]
        path   = self._picker.get_path()
        self._status.busy(f"Divisione in {n} parti…")
        threading.Thread(
            target=self._split_worker, args=(path, points), daemon=True
        ).start()

    def _split_worker(self, src: Path, points: list[int]) -> None:
        results = self._engine.split(src, src.parent, points)
        ok  = sum(1 for r in results if r.success)
        tot = len(results)
        if ok == tot:
            self.after(0, self._status.ok,
                       f"Divisione completata: {ok} file creati")
        else:
            first_err = next((r.error for r in results if not r.success), "")
            self.after(0, self._status.err,
                       f"Divisione: {ok}/{tot} · errore — {first_err}")

    # ── Apply ed Esporta (chain) ──────────────────────────────────────────

    def _run(self) -> None:
        src = self._picker.get_path()
        if not src or not self._info:
            return

        fmt_choice = self._out_fmt_var.get()
        ext = (src.suffix.lower() if fmt_choice == "Stesso del file"
               else AUDIO_FORMATS[fmt_choice].ext)
        fmt = ext.lstrip(".")

        suffix  = self._suffix_entry.get().strip()   # empty = same name
        out_dir = self._out_dir if self._out_dir else src.parent
        output  = out_dir / (src.stem + suffix + ext)

        # Overwrite guard: warn before clobbering an existing file
        # (must be checked on the main thread so the dialog shows correctly).
        if output.exists() and output.resolve() != src.resolve():
            from tkinter import messagebox
            if not messagebox.askyesno(
                "Sovrascrivere?",
                f"Il file esiste già:\n{output.name}\n\nSovrascrivere?",
                icon="warning",
            ):
                return

        voice_effect = self._voice_effect_var.get()
        self._btn_apply.configure(state="disabled")
        self._status.busy("Applicazione effetti…")
        threading.Thread(
            target=self._worker, args=(src, output, fmt, voice_effect), daemon=True
        ).start()

    def _worker(self, src: Path, output: Path, fmt: str,
                voice_effect: str = "none") -> None:
        import shutil
        tmp_a   = safe_tempfile(suffix=src.suffix)
        tmp_b   = safe_tempfile(suffix=src.suffix)
        current = src
        use_a   = True

        def step(fn):
            nonlocal current, use_a
            dst = tmp_a if use_a else tmp_b
            r = fn(current, dst)
            if not r.success:
                self.after(0, self._status.err, r.error)
                return False
            current = dst
            use_a = not use_a
            return True

        try:
            s_ms, e_ms = self._wf.get_trim_range()
            action     = self._sel_action_var.get()

            if action == "trim":
                if not step(lambda c, d: self._engine.trim(c, d, s_ms, e_ms)):
                    return
            elif action == "mute":
                if not step(lambda c, d: self._engine.mute_region(c, d, s_ms, e_ms)):
                    return

            if (self._eq_var.get()
                    and self._deps.scipy and self._deps.soundfile):
                if not step(lambda c, d: self._engine.apply_eq(
                        c, d,
                        bass_db=self._bass.get(),
                        mid_db=self._mid.get(),
                        treble_db=self._treble.get())):
                    return

            gain  = self._gain_slider.get()
            fi_ms = int(self._fi_slider.get() * 1000)
            fo_ms = int(self._fo_slider.get() * 1000)
            if gain != 0 or fi_ms > 0 or fo_ms > 0:
                if not step(lambda c, d: self._engine.adjust(
                        c, d,
                        gain_db=gain, fade_in_ms=fi_ms, fade_out_ms=fo_ms)):
                    return

            if self._speed_var.get() and self._speed_slider.get() != 1.0:
                if not step(lambda c, d: self._engine.change_speed(
                        c, d, speed=self._speed_slider.get())):
                    return

            if voice_effect != "none":
                if not step(lambda c, d, ve=voice_effect:
                            self._engine.apply_voice_effect(c, d, effect=ve)):
                    return

            # Final: to target format
            # Block only when nothing was processed AND output == source
            # (processed output is in a temp file so current != src in that case)
            if current == src and output.resolve() == src.resolve():
                self.after(0, self._status.err,
                           "Nessun effetto attivo e il file di output è lo stesso "
                           "del sorgente. Aggiungi un suffisso o scegli una "
                           "cartella diversa.")
                return

            if current.suffix.lower() != output.suffix.lower():
                r = self._engine.convert(current, output, fmt)
                if not r.success:
                    self.after(0, self._status.err, r.error)
                    return
            else:
                shutil.copy2(str(current), str(output))

            self.after(0, self._status.ok, f"Salvato: {output.name}")

        finally:
            for t in (tmp_a, tmp_b):
                try: t.unlink(missing_ok=True)
                except Exception: pass
            self.after(0, lambda: self._btn_apply.configure(state="normal"))
