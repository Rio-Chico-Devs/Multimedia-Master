"""
Reusable UI primitives for the audio manager.

WaveformCanvas  — interactive tk.Canvas showing a waveform with draggable
                  trim markers and a playhead.  Draws via PIL so no matplotlib
                  dependency is needed.

AudioFileRow    — single file entry in a batch list.

MediaFilePicker — single-file chooser (audio or video) with label + clear.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk


# ── Colours ────────────────────────────────────────────────────────────────────

_WF_BG       = "#141414"
_WF_WAVE     = "#1f6aa5"
_WF_WAVE_LIT = "#4fa8e0"   # brighter inside selection
_WF_SHADE    = "#000000"   # dim outside trim region (paired with stipple="gray50")
_WF_MARKER_S = "#4caf50"   # start marker (green)
_WF_MARKER_E = "#f44336"   # end   marker (red)
_WF_CENTER   = "#2a2a2a"   # centre-line colour
_WF_CURSOR   = "#ffffff"   # playhead cursor colour


# ── WaveformCanvas ─────────────────────────────────────────────────────────────

class WaveformCanvas(tk.Canvas):
    """
    Displays an audio waveform with two draggable trim markers and a playhead.

    Usage:
        wf = WaveformCanvas(parent, height=100,
                            on_trim_change=cb_trim,
                            on_cursor_change=cb_cursor)
        wf.load_peaks(pos_peaks, neg_peaks, duration_ms)
        start_ms, end_ms = wf.get_trim_range()
        cursor_ms = wf.get_cursor()
    """

    HANDLE_R = 6   # half-width of drag handle in pixels

    def __init__(self, parent, height: int = 100,
                 on_trim_change:   Callable[[int, int], None] | None = None,
                 on_cursor_change: Callable[[int], None]       | None = None,
                 **kw):
        kw.setdefault("bg", _WF_BG)
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("height", height)
        super().__init__(parent, **kw)

        self._pos_peaks: list[float] = []
        self._neg_peaks: list[float] = []
        self._duration_ms: int = 0
        self._start_ms:    int = 0
        self._end_ms:      int = 0
        self._cursor_ms:   int = 0
        self._photo:       ImageTk.PhotoImage | None = None
        self._dragging:    str | None = None   # "start", "end", or None

        self._on_trim_change   = on_trim_change
        self._on_cursor_change = on_cursor_change

        self.bind("<Configure>",       self._on_resize)
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_move)
        self.bind("<ButtonRelease-1>", lambda _: setattr(self, "_dragging", None))

    # ── Public API ──────────────────────────────────────────────────────────

    def load_peaks(self, pos: list[float], neg: list[float],
                   duration_ms: int) -> None:
        """Supply waveform data and full duration, then redraw."""
        self._pos_peaks   = pos
        self._neg_peaks   = neg
        self._duration_ms = duration_ms
        self._start_ms    = 0
        self._end_ms      = duration_ms
        self._cursor_ms   = 0
        self._draw()

    def clear(self) -> None:
        self._pos_peaks   = []
        self._neg_peaks   = []
        self._duration_ms = 0
        self._start_ms    = 0
        self._end_ms      = 0
        self._cursor_ms   = 0
        self.delete("all")
        self._photo = None

    def get_trim_range(self) -> tuple[int, int]:
        return self._start_ms, self._end_ms

    def set_trim_range(self, start_ms: int, end_ms: int) -> None:
        self._start_ms = max(0, start_ms)
        self._end_ms   = min(self._duration_ms, end_ms)
        self._draw_overlays()

    def get_cursor(self) -> int:
        return self._cursor_ms

    def set_cursor(self, ms: int) -> None:
        """Move the playhead to the given position (does NOT fire callback)."""
        self._cursor_ms = max(0, min(ms, self._duration_ms))
        self._draw_overlays()

    # ── Drawing ─────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        """Render waveform background into a PIL image, then overlay markers."""
        if not self._pos_peaks:
            return
        w = max(self.winfo_width(), 1)
        h = max(self.winfo_height(), 1)
        mid = h // 2

        img  = Image.new("RGB", (w, h), _WF_BG)
        draw = ImageDraw.Draw(img)

        # Centre line
        draw.line([(0, mid), (w - 1, mid)], fill=_WF_CENTER, width=1)

        # Waveform bars
        n = len(self._pos_peaks)
        for i in range(min(w, n)):
            x   = int(i * w / n)
            x2  = max(x, int((i + 1) * w / n) - 1)
            p   = self._pos_peaks[i]
            neg = self._neg_peaks[i]
            y_t = mid - max(1, int(abs(p)   * (mid - 2)))
            y_b = mid + max(1, int(abs(neg) * (mid - 2)))
            draw.rectangle([x, y_t, x2, y_b], fill=_WF_WAVE)

        self._photo = ImageTk.PhotoImage(img)
        self.delete("waveform")
        self.create_image(0, 0, anchor="nw", image=self._photo, tags="waveform")
        self._draw_overlays()

    def _draw_overlays(self) -> None:
        """Draw trim shading + handles + playhead on top of the waveform."""
        self.delete("overlay")
        if self._duration_ms <= 0:
            return
        w   = max(self.winfo_width(),  1)
        h   = max(self.winfo_height(), 1)
        mid = h // 2
        sx  = int(self._start_ms  / self._duration_ms * w)
        ex  = int(self._end_ms    / self._duration_ms * w)
        cx  = int(self._cursor_ms / self._duration_ms * w)
        r   = self.HANDLE_R

        # Shade outside selection (stipple fakes transparency — Tk has no alpha)
        if sx > 0:
            self.create_rectangle(0, 0, sx, h,
                                  fill=_WF_SHADE, outline="",
                                  stipple="gray50", tags="overlay")
        if ex < w:
            self.create_rectangle(ex, 0, w, h,
                                  fill=_WF_SHADE, outline="",
                                  stipple="gray50", tags="overlay")

        # Marker lines
        self.create_line(sx, 0, sx, h, fill=_WF_MARKER_S, width=2, tags="overlay")
        self.create_line(ex, 0, ex, h, fill=_WF_MARKER_E, width=2, tags="overlay")

        # Drag handles (small rectangles at mid-height)
        self.create_rectangle(sx - r, mid - r*2, sx + r, mid + r*2,
                               fill=_WF_MARKER_S, outline="", tags="overlay")
        self.create_rectangle(ex - r, mid - r*2, ex + r, mid + r*2,
                               fill=_WF_MARKER_E, outline="", tags="overlay")

        # Playhead cursor (thin white line with small top triangle)
        if 0 <= cx <= w:
            self.create_line(cx, 0, cx, h, fill=_WF_CURSOR, width=1,
                             dash=(4, 2), tags="overlay")
            self.create_polygon(cx - 4, 0, cx + 4, 0, cx, 6,
                                fill=_WF_CURSOR, outline="", tags="overlay")

    def _on_resize(self, _=None) -> None:
        if self._pos_peaks:
            self._draw()

    def _on_press(self, event) -> None:
        if self._duration_ms <= 0:
            return
        w  = max(self.winfo_width(), 1)
        sx = int(self._start_ms / self._duration_ms * w)
        ex = int(self._end_ms   / self._duration_ms * w)
        r  = self.HANDLE_R * 3   # wider hit zone

        if abs(event.x - sx) <= r:
            self._dragging = "start"
        elif abs(event.x - ex) <= r:
            self._dragging = "end"
        else:
            # Click on waveform (not on a marker) → move cursor/playhead
            self._dragging = None
            ms = int(max(0, min(event.x, w)) / w * self._duration_ms)
            self._cursor_ms = ms
            self._draw_overlays()
            if self._on_cursor_change:
                self._on_cursor_change(ms)

    def _on_move(self, event) -> None:
        if not self._dragging or self._duration_ms <= 0:
            return
        w  = max(self.winfo_width(), 1)
        ms = int(max(0, min(event.x, w)) / w * self._duration_ms)
        GAP = 100   # minimum gap between markers (ms)

        if self._dragging == "start":
            self._start_ms = min(ms, self._end_ms - GAP)
        else:
            self._end_ms = max(ms, self._start_ms + GAP)
        self._draw_overlays()
        if self._on_trim_change:
            self._on_trim_change(self._start_ms, self._end_ms)


# ── MediaFilePicker ────────────────────────────────────────────────────────────

class MediaFilePicker(ctk.CTkFrame):
    """
    Single-file picker: label + path display + browse button + clear.

    on_change(path | None) is called whenever the selection changes.
    """

    def __init__(self, parent,
                 label:     str                = "File",
                 exts:      set[str] | None    = None,
                 on_change: Callable | None    = None,
                 **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._exts      = exts       # e.g. {".mp4", ".mkv"}
        self._on_change = on_change or (lambda p: None)
        self._path: Path | None = None
        self._build(label)

    def _build(self, label: str) -> None:
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text=label, width=80, anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).grid(
            row=0, column=0, padx=(0, 8))

        self._path_lbl = ctk.CTkLabel(
            self, text="Nessun file selezionato",
            anchor="w", text_color="gray",
            font=ctk.CTkFont(size=11))
        self._path_lbl.grid(row=0, column=1, sticky="ew")

        ctk.CTkButton(self, text="Sfoglia", width=72, height=28,
                      command=self._browse).grid(row=0, column=2, padx=(8, 0))
        ctk.CTkButton(self, text="✕", width=30, height=28,
                      fg_color="#2a2a2a", hover_color="#3a3a3a",
                      command=self._clear).grid(row=0, column=3, padx=(4, 0))

    def _browse(self) -> None:
        from tkinter import filedialog
        if self._exts:
            ft = [("Media", " ".join(f"*{e}" for e in sorted(self._exts))),
                  ("Tutti", "*.*")]
        else:
            ft = [("Tutti i file", "*.*")]
        p = filedialog.askopenfilename(filetypes=ft)
        if p:
            self._set(Path(p))

    def _clear(self) -> None:
        self._set(None)

    def _set(self, path: Path | None) -> None:
        self._path = path
        if path:
            self._path_lbl.configure(text=path.name, text_color="white")
        else:
            self._path_lbl.configure(text="Nessun file selezionato",
                                     text_color="gray")
        self._on_change(path)

    def get_path(self) -> Path | None:
        return self._path
