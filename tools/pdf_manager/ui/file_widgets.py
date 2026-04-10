"""
Reusable file-list widgets for the PDF manager.

  ImageFileList   — drag-and-drop list of images (for Convert tab)
  PdfMergeList    — reorderable list of PDFs (for Merge tab)
  SingleFilePicker — one-file picker with a clear button (Split/Protect/Analyze)
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import customtkinter as ctk

# Optional drag-and-drop support
try:
    import tkinterdnd2 as dnd
    _DND = True
except ImportError:
    _DND = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif",
              ".tiff", ".tif", ".bmp", ".gif"}
PDF_EXT    = ".pdf"


# ── helpers ───────────────────────────────────────────────────────────────────

def _human_size(n: int) -> str:
    if n < 1024:        return f"{n} B"
    if n < 1024**2:     return f"{n/1024:.1f} KB"
    return              f"{n/1024**2:.1f} MB"


# ══════════════════════════════════════════════════════════════════════════════
# ImageFileList
# ══════════════════════════════════════════════════════════════════════════════

class _ImgRow(ctk.CTkFrame):
    """One row in the ImageFileList."""

    COLOR_NORMAL   = "transparent"
    COLOR_SELECTED = "#1f3a5c"

    def __init__(self, parent, path: Path, on_select: Callable, **kw):
        kw.setdefault("corner_radius", 6)
        super().__init__(parent, fg_color=self.COLOR_NORMAL, **kw)
        self.path      = path
        self._on_sel   = on_select
        self.selected  = False

        ctk.CTkLabel(self, text="🖼", font=ctk.CTkFont(size=18),
                     width=28).pack(side="left", padx=(6, 0))
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkLabel(info, text=path.name, anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(fill="x")
        size_str = _human_size(path.stat().st_size)
        ctk.CTkLabel(info, text=size_str, anchor="w",
                     text_color="gray",
                     font=ctk.CTkFont(size=10)).pack(fill="x")

        for w in [self, *self.winfo_children(), *info.winfo_children()]:
            w.bind("<Button-1>", self._click)

    def _click(self, _=None):
        self._on_sel(self)

    def set_selected(self, val: bool):
        self.selected = val
        self.configure(fg_color=self.COLOR_SELECTED if val else self.COLOR_NORMAL)


class ImageFileList(ctk.CTkFrame):
    """
    Scrollable list of image files.
    Supports browse dialog, folder scan, and (if tkinterdnd2 is installed)
    drag-and-drop.

    Public API:
      .get_paths() -> list[Path]
      .clear()
      .remove_selected()
    """

    def __init__(self, parent, **kw):
        kw.setdefault("corner_radius", 10)
        super().__init__(parent, **kw)
        self._paths:   list[Path]    = []
        self._rows:    list[_ImgRow] = []
        self._selected: _ImgRow | None = None
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        # Toolbar
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(bar, text="Immagini da convertire",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(side="left")
        ctk.CTkButton(bar, text="✕ Rimuovi", width=88, height=26,
                      fg_color="#3a1f1f", hover_color="#5c2a2a",
                      command=self.remove_selected).pack(side="right")
        ctk.CTkButton(bar, text="+ Cartella", width=88, height=26,
                      command=self._browse_folder).pack(side="right", padx=(0, 6))
        ctk.CTkButton(bar, text="+ File", width=72, height=26,
                      command=self._browse_files).pack(side="right", padx=(0, 4))

        # Drop zone / scroll area
        self._drop_label = ctk.CTkLabel(
            self,
            text="Trascina immagini qui\noppure usa i bottoni sopra",
            text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self._scroll = ctk.CTkScrollableFrame(self, corner_radius=6)
        self._scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._show_placeholder()

        # DnD
        if _DND:
            try:
                self._scroll.drop_target_register(dnd.DND_FILES)  # type: ignore
                self._scroll.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _show_placeholder(self):
        for w in self._scroll.winfo_children():
            w.destroy()
        if not self._paths:
            self._drop_label = ctk.CTkLabel(
                self._scroll,
                text="Trascina immagini qui\noppure usa i bottoni sopra",
                text_color="gray",
                font=ctk.CTkFont(size=12),
            )
            self._drop_label.pack(pady=30)

    # ── Browsing ──────────────────────────────────────────────────────────────

    def _browse_files(self):
        from tkinter import filedialog
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        paths = filedialog.askopenfilenames(
            title="Seleziona immagini",
            filetypes=[("Immagini", exts), ("Tutti i file", "*.*")],
        )
        if paths:
            self._add_paths([Path(p) for p in paths])

    def _browse_folder(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Seleziona cartella")
        if folder:
            imgs = [p for p in Path(folder).rglob("*")
                    if p.suffix.lower() in IMAGE_EXTS]
            self._add_paths(sorted(imgs))

    def _on_drop(self, event):
        raw = event.data
        # tkinterdnd2 wraps paths with braces when they contain spaces
        paths = []
        for token in raw.strip().split():
            token = token.strip("{}")
            p = Path(token)
            if p.suffix.lower() in IMAGE_EXTS and p.is_file():
                paths.append(p)
        self._add_paths(paths)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _add_paths(self, new_paths: list[Path]):
        seen = set(self._paths)
        added = [p for p in new_paths if p not in seen]
        if not added:
            return
        self._paths.extend(added)
        # Clear placeholder if needed
        if len(self._paths) == len(added):
            for w in self._scroll.winfo_children():
                w.destroy()
        for p in added:
            row = _ImgRow(self._scroll, p, self._on_row_select)
            row.pack(fill="x", pady=2)
            self._rows.append(row)

    def _on_row_select(self, row: _ImgRow):
        if self._selected and self._selected is not row:
            self._selected.set_selected(False)
        row.set_selected(not row.selected)
        self._selected = row if row.selected else None

    # ── Public API ────────────────────────────────────────────────────────────

    def get_paths(self) -> list[Path]:
        return list(self._paths)

    def clear(self):
        self._paths.clear()
        self._rows.clear()
        self._selected = None
        self._show_placeholder()

    def remove_selected(self):
        if not self._selected:
            return
        row  = self._selected
        path = row.path
        row.destroy()
        self._rows.remove(row)
        self._paths.remove(path)
        self._selected = None
        if not self._paths:
            self._show_placeholder()


# ══════════════════════════════════════════════════════════════════════════════
# PdfMergeList
# ══════════════════════════════════════════════════════════════════════════════

class _PdfRow(ctk.CTkFrame):
    """One row in the PdfMergeList."""

    COLOR_NORMAL   = "transparent"
    COLOR_SELECTED = "#1f3a5c"

    def __init__(self, parent, path: Path, index: int,
                 on_select: Callable, **kw):
        kw.setdefault("corner_radius", 6)
        super().__init__(parent, fg_color=self.COLOR_NORMAL, **kw)
        self.path     = path
        self._on_sel  = on_select
        self.selected = False

        self._num_lbl = ctk.CTkLabel(
            self, text=str(index), width=24,
            font=ctk.CTkFont(size=11), text_color="gray")
        self._num_lbl.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(self, text="📄", font=ctk.CTkFont(size=16),
                     width=24).pack(side="left", padx=4)
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text=path.name, anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(fill="x")
        size_str = _human_size(path.stat().st_size)
        ctk.CTkLabel(info, text=size_str, anchor="w",
                     text_color="gray",
                     font=ctk.CTkFont(size=10)).pack(fill="x")

        for w in [self, *self.winfo_children(), *info.winfo_children()]:
            w.bind("<Button-1>", self._click)

    def _click(self, _=None):
        self._on_sel(self)

    def set_selected(self, val: bool):
        self.selected = val
        self.configure(fg_color=self.COLOR_SELECTED if val else self.COLOR_NORMAL)

    def set_index(self, i: int):
        self._num_lbl.configure(text=str(i))


class PdfMergeList(ctk.CTkFrame):
    """
    Reorderable list of PDF files for merging.

    Public API:
      .get_paths() -> list[Path]   (in display order)
      .clear()
    """

    def __init__(self, parent, **kw):
        kw.setdefault("corner_radius", 10)
        super().__init__(parent, **kw)
        self._paths:    list[Path]    = []
        self._rows:     list[_PdfRow] = []
        self._selected: _PdfRow | None = None
        self._build()

    def _build(self):
        # Toolbar
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(bar, text="File PDF da unire",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(side="left")
        ctk.CTkButton(bar, text="✕", width=32, height=26,
                      fg_color="#3a1f1f", hover_color="#5c2a2a",
                      command=self._remove_selected).pack(side="right")
        ctk.CTkButton(bar, text="↓", width=32, height=26,
                      command=self._move_down).pack(side="right", padx=(0, 4))
        ctk.CTkButton(bar, text="↑", width=32, height=26,
                      command=self._move_up).pack(side="right", padx=(0, 4))
        ctk.CTkButton(bar, text="+ PDF", width=72, height=26,
                      command=self._browse).pack(side="right", padx=(0, 8))

        self._scroll = ctk.CTkScrollableFrame(self, corner_radius=6)
        self._scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._show_placeholder()

        if _DND:
            try:
                self._scroll.drop_target_register(dnd.DND_FILES)  # type: ignore
                self._scroll.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _show_placeholder(self):
        for w in self._scroll.winfo_children():
            w.destroy()
        if not self._paths:
            ctk.CTkLabel(self._scroll,
                         text="Trascina PDF qui oppure usa "+ PDF_EXT + " File",
                         text_color="gray",
                         font=ctk.CTkFont(size=12)).pack(pady=30)

    def _browse(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="Seleziona PDF",
            filetypes=[("PDF", "*.pdf"), ("Tutti i file", "*.*")],
        )
        if paths:
            self._add_paths([Path(p) for p in paths])

    def _on_drop(self, event):
        raw = event.data
        paths = []
        for token in raw.strip().split():
            token = token.strip("{}")
            p = Path(token)
            if p.suffix.lower() == PDF_EXT and p.is_file():
                paths.append(p)
        self._add_paths(paths)

    def _add_paths(self, new_paths: list[Path]):
        seen = set(self._paths)
        added = [p for p in new_paths if p not in seen]
        if not added:
            return
        if not self._paths:
            for w in self._scroll.winfo_children():
                w.destroy()
        for p in added:
            self._paths.append(p)
            idx = len(self._paths)
            row = _PdfRow(self._scroll, p, idx, self._on_row_select)
            row.pack(fill="x", pady=2)
            self._rows.append(row)

    def _on_row_select(self, row: _PdfRow):
        if self._selected and self._selected is not row:
            self._selected.set_selected(False)
        row.set_selected(not row.selected)
        self._selected = row if row.selected else None

    def _selected_idx(self) -> int | None:
        if not self._selected:
            return None
        try:
            return self._rows.index(self._selected)
        except ValueError:
            return None

    def _repack(self):
        for row in self._rows:
            row.pack_forget()
        for i, row in enumerate(self._rows):
            row.set_index(i + 1)
            row.pack(fill="x", pady=2)

    def _move_up(self):
        i = self._selected_idx()
        if i is None or i == 0:
            return
        self._rows[i], self._rows[i-1]   = self._rows[i-1], self._rows[i]
        self._paths[i], self._paths[i-1] = self._paths[i-1], self._paths[i]
        self._repack()

    def _move_down(self):
        i = self._selected_idx()
        if i is None or i >= len(self._rows) - 1:
            return
        self._rows[i], self._rows[i+1]   = self._rows[i+1], self._rows[i]
        self._paths[i], self._paths[i+1] = self._paths[i+1], self._paths[i]
        self._repack()

    def _remove_selected(self):
        i = self._selected_idx()
        if i is None:
            return
        self._rows[i].destroy()
        self._rows.pop(i)
        self._paths.pop(i)
        self._selected = None
        if not self._paths:
            self._show_placeholder()
        else:
            self._repack()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_paths(self) -> list[Path]:
        return list(self._paths)

    def clear(self):
        self._paths.clear()
        self._rows.clear()
        self._selected = None
        self._show_placeholder()


# ══════════════════════════════════════════════════════════════════════════════
# SingleFilePicker
# ══════════════════════════════════════════════════════════════════════════════

class SingleFilePicker(ctk.CTkFrame):
    """
    A one-line file picker for a single PDF.
    Shows the chosen path and a clear button.

    Public API:
      .get_path() -> Path | None
      .set_path(path: Path)
      .clear()
      .on_change: Callable[[Path | None], None]  (assign to hook changes)
    """

    def __init__(self, parent, label: str = "File PDF",
                 on_change: Callable[[Path | None], None] | None = None, **kw):
        kw.setdefault("corner_radius", 10)
        super().__init__(parent, **kw)
        self._path:      Path | None = None
        self.on_change   = on_change or (lambda _: None)
        self._build(label)

    def _build(self, label: str):
        ctk.CTkLabel(self, text=label,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x", padx=10, pady=(8, 4))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 8))
        row.grid_columnconfigure(0, weight=1)

        self._path_lbl = ctk.CTkLabel(
            row,
            text="Nessun file selezionato",
            anchor="w",
            text_color="gray",
            font=ctk.CTkFont(size=11),
        )
        self._path_lbl.grid(row=0, column=0, sticky="ew")

        ctk.CTkButton(row, text="✕", width=28, height=28,
                      fg_color="#3a1f1f", hover_color="#5c2a2a",
                      command=self.clear).grid(row=0, column=2, padx=(6, 0))
        ctk.CTkButton(row, text="Sfoglia", width=72, height=28,
                      command=self._browse).grid(row=0, column=1, padx=(6, 0))

        # DnD on the label area
        if _DND:
            try:
                self._path_lbl.drop_target_register(dnd.DND_FILES)  # type: ignore
                self._path_lbl.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _browse(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(
            title="Seleziona PDF",
            filetypes=[("PDF", "*.pdf"), ("Tutti i file", "*.*")],
        )
        if p:
            self.set_path(Path(p))

    def _on_drop(self, event):
        raw = event.data
        for token in raw.strip().split():
            token = token.strip("{}")
            p = Path(token)
            if p.suffix.lower() == PDF_EXT and p.is_file():
                self.set_path(p)
                return

    def get_path(self) -> Path | None:
        return self._path

    def set_path(self, path: Path):
        self._path = path
        self._path_lbl.configure(text=str(path), text_color="white")
        self.on_change(path)

    def clear(self):
        self._path = None
        self._path_lbl.configure(text="Nessun file selezionato", text_color="gray")
        self.on_change(None)
