"""
Edit Tab — interactive audio manipulation with waveform display.

Features (all combinable before exporting once):
  • Waveform view with draggable trim markers
  • Trim / cut to selection
  • Volume gain  (±20 dB)
  • Fade in / fade out  (0–10 s)
  • 3-band EQ: bass / mid / treble  (±12 dB)   — needs scipy
  • Speed change  (0.5×–2×)
  • Export to same format or new format
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from common.ui.widgets import SectionLabel, Separator, StatusBar
from core.audio_engine import AudioEngine, AudioInfo
from core.dependencies import DepStatus
from core.formats import AUDIO_EXTS, AUDIO_FORMATS
from .widgets import MediaFilePicker, WaveformCanvas


class EditTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, deps: DepStatus, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine   = engine
        self._deps     = deps
        self._info: AudioInfo | None = None
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ── File picker ──────────────────────────────────────────────────
        self._picker = MediaFilePicker(
            self, label="File audio",
            exts=AUDIO_EXTS,
            on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew",
                          padx=12, pady=(12, 0))

        # ── Waveform ─────────────────────────────────────────────────────
        wf_frame = ctk.CTkFrame(self, fg_color=("#0d0d0d", "#0d0d0d"),
                                 corner_radius=8)
        wf_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 0))
        wf_frame.grid_columnconfigure(0, weight=1)

        self._wf = WaveformCanvas(wf_frame, height=110)
        self._wf.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        self._wf_info = ctk.CTkLabel(
            wf_frame,
            text="Apri un file audio per visualizzare la forma d'onda",
            text_color="#555", font=ctk.CTkFont(size=10))
        self._wf_info.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 4))

        # ── Controls ─────────────────────────────────────────────────────
        ctrl_sf = ctk.CTkScrollableFrame(
            self, fg_color=("#111", "#111"), corner_radius=10)
        ctrl_sf.grid(row=2, column=0, sticky="nsew", padx=12, pady=(8, 0))
        ctrl_sf.grid_columnconfigure((0, 1, 2), weight=1)

        self._build_trim_section(ctrl_sf)
        self._build_volume_section(ctrl_sf)
        self._build_eq_section(ctrl_sf)
        self._build_speed_section(ctrl_sf)
        self._build_output_section(ctrl_sf)

        # ── Bottom bar ────────────────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 0))
        bot.grid_columnconfigure(0, weight=1)
        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")
        self._btn_apply = ctk.CTkButton(
            bot, text="💾  Applica ed Esporta",
            width=180, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._run)
        self._btn_apply.grid(row=0, column=1, padx=(8, 0))

    # ── Control sections ───────────────────────────────────────────────────

    def _build_trim_section(self, parent) -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        frame.grid_columnconfigure(0, weight=1)

        SectionLabel(frame, "✂  Taglia").pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(frame,
                     text="Trascina i marcatori sulla\n"
                          "forma d'onda per selezionare\n"
                          "la sezione da mantenere.",
                     text_color="#777", font=ctk.CTkFont(size=10),
                     justify="left").pack(anchor="w")

        self._trim_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame, text="Abilita taglio",
                        variable=self._trim_var).pack(anchor="w", pady=(8, 0))

        self._trim_lbl = ctk.CTkLabel(
            frame, text="—", text_color="#777",
            font=ctk.CTkFont(size=10), anchor="w")
        self._trim_lbl.pack(fill="x", pady=(4, 0))

    def _build_volume_section(self, parent) -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        frame.grid_columnconfigure(0, weight=1)

        SectionLabel(frame, "🔊  Volume & Fade").pack(fill="x", pady=(0, 4))

        self._gain_lbl = ctk.CTkLabel(
            frame, text="Gain: 0 dB", anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"))
        self._gain_lbl.pack(fill="x")
        self._gain_slider = ctk.CTkSlider(
            frame, from_=-20, to=20, number_of_steps=40,
            command=lambda v: self._gain_lbl.configure(
                text=f"Gain: {v:+.0f} dB"))
        self._gain_slider.set(0)
        self._gain_slider.pack(fill="x", pady=(2, 10))

        self._fi_lbl = ctk.CTkLabel(
            frame, text="Fade in: 0 s", anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"))
        self._fi_lbl.pack(fill="x")
        self._fi_slider = ctk.CTkSlider(
            frame, from_=0, to=10, number_of_steps=100,
            command=lambda v: self._fi_lbl.configure(
                text=f"Fade in: {v:.1f} s"))
        self._fi_slider.set(0)
        self._fi_slider.pack(fill="x", pady=(2, 10))

        self._fo_lbl = ctk.CTkLabel(
            frame, text="Fade out: 0 s", anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"))
        self._fo_lbl.pack(fill="x")
        self._fo_slider = ctk.CTkSlider(
            frame, from_=0, to=10, number_of_steps=100,
            command=lambda v: self._fo_lbl.configure(
                text=f"Fade out: {v:.1f} s"))
        self._fo_slider.set(0)
        self._fo_slider.pack(fill="x", pady=(2, 0))

    def _build_eq_section(self, parent) -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=2, sticky="nsew", padx=8, pady=8)
        frame.grid_columnconfigure(0, weight=1)

        SectionLabel(frame, "🎚  Equalizzatore").pack(fill="x", pady=(0, 4))

        eq_ok = self._deps.soundfile and self._deps.scipy and self._deps.numpy
        if not eq_ok:
            ctk.CTkLabel(
                frame,
                text="⚠  Richiede:\npip install soundfile scipy numpy",
                text_color="#f44336", font=ctk.CTkFont(size=10),
                justify="left",
            ).pack(anchor="w", pady=(0, 6))

        state = "normal" if eq_ok else "disabled"
        self._eq_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame, text="Abilita EQ",
                        variable=self._eq_var,
                        state=state).pack(anchor="w", pady=(0, 6))

        for attr, label, row_ in [
            ("_bass",   "Bassi   (<250 Hz)",   1),
            ("_mid",    "Medi    (250–4kHz)",  2),
            ("_treble", "Acuti   (>4 kHz)",    3),
        ]:
            lbl = ctk.CTkLabel(frame, text=f"{label}: 0 dB",
                                anchor="w", font=ctk.CTkFont(size=10))
            lbl.pack(fill="x")
            slider = ctk.CTkSlider(
                frame, from_=-12, to=12, number_of_steps=24,
                state=state,
                command=lambda v, l=lbl, n=label: l.configure(
                    text=f"{n}: {v:+.0f} dB"))
            slider.set(0)
            slider.pack(fill="x", pady=(2, 6))
            setattr(self, attr + "_lbl", lbl)
            setattr(self, attr, slider)

    def _build_speed_section(self, parent) -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        SectionLabel(frame, "⏩  Velocità").pack(anchor="w", pady=(0, 4))
        self._speed_lbl = ctk.CTkLabel(
            frame, text="Velocità: 1.0×", anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"))
        self._speed_lbl.pack(anchor="w")
        self._speed_slider = ctk.CTkSlider(
            frame, from_=0.5, to=2.0, number_of_steps=30,
            command=lambda v: self._speed_lbl.configure(
                text=f"Velocità: {v:.2f}×"))
        self._speed_slider.set(1.0)
        self._speed_slider.pack(fill="x", padx=(0, 0), pady=(2, 0))

        self._speed_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame, text="Abilita cambio velocità",
                        variable=self._speed_var).pack(anchor="w", pady=(6, 0))

    def _build_output_section(self, parent) -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=1, column=1, columnspan=2, sticky="nsew",
                   padx=8, pady=(0, 8))
        frame.grid_columnconfigure(0, weight=1)

        SectionLabel(frame, "💾  Output").pack(anchor="w", pady=(0, 4))

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x")
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(row, text="Formato:", width=70, anchor="w",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0)
        self._out_fmt_var = ctk.StringVar(value="Stesso del file")
        ctk.CTkOptionMenu(
            row, variable=self._out_fmt_var,
            values=["Stesso del file"] + list(AUDIO_FORMATS.keys()),
            dynamic_resizing=False,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ctk.CTkLabel(row, text="Suffisso:", width=70, anchor="w",
                     font=ctk.CTkFont(size=11)).grid(
            row=1, column=0, pady=(6, 0))
        self._suffix_entry = ctk.CTkEntry(
            row, placeholder_text="_modificato")
        self._suffix_entry.insert(0, "_modificato")
        self._suffix_entry.grid(row=1, column=1, sticky="ew",
                                padx=(4, 0), pady=(6, 0))

    # ── File loaded ────────────────────────────────────────────────────────

    def _on_file_change(self, path: Path | None) -> None:
        if not path:
            self._wf.clear()
            self._wf_info.configure(
                text="Apri un file audio per visualizzare la forma d'onda")
            if hasattr(self, "_btn_apply"):
                self._btn_apply.configure(state="disabled")
            return

        self._status.busy("Caricamento forma d'onda…")
        threading.Thread(
            target=self._load_waveform, args=(path,), daemon=True
        ).start()

    def _load_waveform(self, path: Path) -> None:
        info = self._engine.probe(path)
        self._info = info
        pos, neg = self._engine.get_waveform_peaks(path, num_samples=900)
        dur_ms    = int(info.duration_s * 1000)

        def _apply():
            self._wf.load_peaks(pos, neg, dur_ms)
            mins  = int(info.duration_s // 60)
            secs  = info.duration_s % 60
            self._wf_info.configure(
                text=f"{info.format.upper()}  ·  "
                     f"{info.sample_rate} Hz  ·  "
                     f"{'Stereo' if info.channels == 2 else 'Mono'}  ·  "
                     f"{mins}:{secs:04.1f}  ·  "
                     f"{info.bitrate_kbps} kbps",
                text_color="#aaa",
            )
            self._btn_apply.configure(state="normal")
            self._status.info(
                "Modifica i parametri e premi 'Applica ed Esporta'")

        self.after(0, _apply)

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        src = self._picker.get_path()
        if not src:
            return

        fmt_choice = self._out_fmt_var.get()
        ext = (src.suffix.lower() if fmt_choice == "Stesso del file"
               else AUDIO_FORMATS[fmt_choice].ext)
        fmt = ext.lstrip(".")

        suffix = self._suffix_entry.get().strip() or "_modificato"
        output = src.parent / (src.stem + suffix + ext)

        self._btn_apply.configure(state="disabled")
        self._status.busy("Applicazione effetti…")
        threading.Thread(
            target=self._worker, args=(src, output, fmt), daemon=True
        ).start()

    def _worker(self, src: Path, output: Path, fmt: str) -> None:
        from pathlib import Path as _P
        import tempfile, shutil

        # Chain operations through temp files
        tmp1 = _P(tempfile.mktemp(suffix=output.suffix))
        tmp2 = _P(tempfile.mktemp(suffix=output.suffix))
        current = src

        try:
            # Step 1: Trim
            if self._trim_var.get() and self._wf._duration_ms > 0:
                s_ms, e_ms = self._wf.get_trim_range()
                result = self._engine.trim(current, tmp1, s_ms, e_ms)
                if not result.success:
                    self.after(0, self._status.err, result.error)
                    return
                current = tmp1

            # Step 2: EQ
            if (self._eq_var.get()
                    and self._deps.scipy and self._deps.soundfile):
                dst = tmp2 if current == tmp1 else tmp1
                result = self._engine.apply_eq(
                    current, dst,
                    bass_db=self._bass.get(),
                    mid_db=self._mid.get(),
                    treble_db=self._treble.get(),
                )
                if not result.success:
                    self.after(0, self._status.err, result.error)
                    return
                current = dst

            # Step 3: Volume + Fade
            gain   = self._gain_slider.get()
            fi_ms  = int(self._fi_slider.get()  * 1000)
            fo_ms  = int(self._fo_slider.get()  * 1000)
            if gain != 0 or fi_ms > 0 or fo_ms > 0:
                dst = tmp2 if current in (tmp1,) else tmp1
                if current == tmp2: dst = tmp1
                result = self._engine.adjust(
                    current, dst,
                    gain_db=gain, fade_in_ms=fi_ms, fade_out_ms=fo_ms)
                if not result.success:
                    self.after(0, self._status.err, result.error)
                    return
                current = dst

            # Step 4: Speed
            if self._speed_var.get() and self._speed_slider.get() != 1.0:
                dst = tmp2 if current == tmp1 else tmp1
                result = self._engine.change_speed(
                    current, dst, speed=self._speed_slider.get())
                if not result.success:
                    self.after(0, self._status.err, result.error)
                    return
                current = dst

            # Final: convert to target format if needed
            if current.suffix.lower() != output.suffix.lower():
                result = self._engine.convert(current, output, fmt)
                if not result.success:
                    self.after(0, self._status.err, result.error)
                    return
            else:
                shutil.copy2(str(current), str(output))

            self.after(0, self._status.ok, f"Salvato: {output.name}")

        finally:
            for t in (tmp1, tmp2):
                try:
                    t.unlink(missing_ok=True)
                except Exception:
                    pass
            self.after(0, self._btn_apply.configure, {"state": "normal"})
