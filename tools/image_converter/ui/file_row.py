import threading
import customtkinter as ctk
from pathlib import Path
from PIL import Image
from typing import Callable

from core.formats import ConversionResult


class FileRow(ctk.CTkFrame):
    """
    Displays a single queued file: thumbnail, name, size, dimensions,
    a remove button, and a status label updated after conversion.
    Supports click-to-select with visual highlight.
    Thumbnail is decoded in a background thread — widget creation is instant.
    """

    THUMB_SIZE     = 48
    COLOR_NORMAL   = "transparent"
    COLOR_SELECTED = "#1f3a5c"

    def __init__(
        self,
        parent,
        file_path: Path,
        on_remove:  Callable,
        on_select:  Callable | None = None,
        on_drag_start:  Callable | None = None,
        on_drag_motion: Callable | None = None,
        on_drag_end:    Callable | None = None,
        **kw,
    ):
        super().__init__(parent, corner_radius=8, **kw)
        self.file_path  = file_path
        self._on_select = on_select
        self._on_drag_start  = on_drag_start
        self._on_drag_motion = on_drag_motion
        self._on_drag_end    = on_drag_end
        self._result:   ConversionResult | None = None
        self._selected  = False
        self._dims      = ""
        self._build(on_remove)
        # Kick off thumbnail decode — never blocks the main thread.
        threading.Thread(target=self._load_thumb, daemon=True).start()

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh_name(self) -> None:
        """Re-read name/size after the file was renamed or moved on disk."""
        self._name_lbl.configure(text=self.file_path.name)
        self._subtitle_lbl.configure(text=self._subtitle())

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def result(self) -> ConversionResult | None:
        return self._result

    def set_status(self, text: str, color: str = "gray") -> None:
        self._status_lbl.configure(text=text, text_color=color)

    def apply_result(self, result: ConversionResult) -> None:
        self._result = result
        if not result.success:
            self.set_status("✗ errore", "#f44336")
            return
        d = result.delta_pct
        if d > 0:
            self.set_status(f"✓ -{d}%", "#4caf50")
        elif d < 0:
            self.set_status(f"✓ +{-d}%", "#ff9800")
        else:
            self.set_status("✓", "#4caf50")

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        color = self.COLOR_SELECTED if selected else self.COLOR_NORMAL
        self.configure(fg_color=color)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self, on_remove) -> None:
        s = self.THUMB_SIZE

        # Drag handle — grab here to reorder the queue.
        self._handle = ctk.CTkLabel(
            self, text="⠿", width=16, text_color="#666",
            font=ctk.CTkFont(size=16), cursor="fleur")
        self._handle.pack(side="left", padx=(8, 0), pady=8)
        if self._on_drag_start:
            self._handle.bind("<ButtonPress-1>",
                              lambda e: self._on_drag_start(self, e))
            self._handle.bind("<B1-Motion>",
                              lambda e: self._on_drag_motion(self, e))
            self._handle.bind("<ButtonRelease-1>",
                              lambda e: self._on_drag_end(self, e))

        # Placeholder shown while thumbnail loads in background.
        self._thumb_lbl = ctk.CTkLabel(
            self, text="🖼", font=ctk.CTkFont(size=22), width=s)
        self._thumb_lbl.pack(side="left", padx=(6, 6), pady=8)

        self._add_info()

        self._status_lbl = ctk.CTkLabel(self, text="", width=80,
                                        font=ctk.CTkFont(size=12))
        self._status_lbl.pack(side="right", padx=6)

        ctk.CTkButton(
            self, text="✕", width=30, height=30,
            fg_color="transparent", hover_color="#3a3a3a",
            command=lambda: on_remove(self),
        ).pack(side="right", padx=(0, 8))

        self.bind("<Button-1>", self._on_click)
        for child in self.winfo_children():
            # The drag handle owns Button-1 for reordering; don't override it.
            if child is self._handle:
                continue
            child.bind("<Button-1>", self._on_click)

    def _add_info(self) -> None:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(side="left", fill="x", expand=True)

        self._name_lbl = ctk.CTkLabel(
            frame, text=self.file_path.name, anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._name_lbl.pack(fill="x")

        self._subtitle_lbl = ctk.CTkLabel(
            frame, text=self._subtitle(),
            anchor="w", text_color="gray",
            font=ctk.CTkFont(size=11),
        )
        self._subtitle_lbl.pack(fill="x")

    def _subtitle(self) -> str:
        size_b   = self.file_path.stat().st_size
        size_str = (f"{size_b / 1024:.0f} KB" if size_b < 1_048_576
                    else f"{size_b / 1_048_576:.2f} MB")
        fmt = self.file_path.suffix[1:].upper()
        dims = f"  ·  {self._dims}" if self._dims else ""
        return f"{size_str}  ·  {fmt}{dims}"

    # ── Async thumbnail loading ────────────────────────────────────────────────

    def _load_thumb(self) -> None:
        s = self.THUMB_SIZE
        try:
            pil = Image.open(self.file_path)
            w, h = pil.width, pil.height
            pil.draft("RGB", (s * 2, s * 2))
            pil.thumbnail((s, s), Image.LANCZOS)
            self.after(0, self._update_thumb, pil, f"{w}×{h} px")
        except Exception:
            pass

    def _update_thumb(self, pil: Image.Image, dims: str) -> None:
        try:
            if not self.winfo_exists():
                return
            s = self.THUMB_SIZE
            self._dims = dims
            self._thumb = ctk.CTkImage(pil, size=(min(s, pil.width), min(s, pil.height)))
            self._thumb_lbl.configure(image=self._thumb, text="")
            self._subtitle_lbl.configure(text=self._subtitle())
        except Exception:
            pass

    def _on_click(self, _event=None) -> None:
        if self._on_select:
            self._on_select(self)
