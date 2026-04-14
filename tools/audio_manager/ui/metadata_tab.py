"""
Metadata Tab — deep metadata inspector, editor and forensic wipe.

Features:
  • Multi-file list — click a file to load ALL its metadata fields
  • Deep reading: every ID3 frame, MP4 atom, Vorbis key, FLAC block
  • Fields grouped by category: Standard / Tecnici / ⚠ Storico / ⚠ Nascosti / Info
  • Inline editing of every text field
  • Per-field delete button (✕) — queued until "Salva modifiche"
  • "Applica a tutti" — apply current field values to every file in the list
  • "Wipe completo" — ffmpeg remux -map_metadata -1 + mutagen clear
  • "Analizza" — health & safety check (magic bytes, ffmpeg decode, tag scan)
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from common.ui.widgets import SectionLabel, Separator, StatusBar
from core.audio_engine import AudioEngine
from core.dependencies import DepStatus
from core.formats import AUDIO_EXTS


# ── Category display config ────────────────────────────────────────────────────
_CAT_ORDER = ["standard", "technical", "history", "hidden", "custom", "art", "info"]

_CAT_LABELS = {
    "standard":  ("Tag standard",                        "#ffffff"),
    "technical": ("Tecnici",                             "#aaaaaa"),
    "history":   ("⚠  Storico / Provenienza",            "#e8a020"),
    "hidden":    ("⚠  Dati nascosti / privati",          "#e04040"),
    "custom":    ("Tag personalizzati",                  "#aaaaff"),
    "art":       ("Immagini incorporate",                "#aaaaaa"),
    "info":      ("Informazioni file (sola lettura)",    "#666666"),
}

_BTN_DARK = {"fg_color": "#2a2a2a", "hover_color": "#3a3a3a"}


class MetadataTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, deps: DepStatus, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine    = engine
        self._deps      = deps
        self._files:    list[Path] = []
        self._sel_idx:  int | None = None
        self._rows:     list[ctk.CTkFrame] = []
        # Per-field widgets and pending changes
        self._field_entries:  dict[str, ctk.CTkEntry] = {}   # raw_key → Entry
        self._pending_delete: set[str]                 = set()
        self._field_rows:     dict[str, ctk.CTkFrame]  = {}  # raw_key → row frame
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        if not self._deps.mutagen:
            ctk.CTkLabel(
                self,
                text="⚠  Questa funzione richiede mutagen.\n\n"
                     "Installa con:  pip install mutagen\n\n"
                     "Poi riavvia Multimedia Master.",
                font=ctk.CTkFont(size=12),
                text_color="#f44336",
                justify="left",
            ).grid(row=0, column=0, padx=40, pady=40, sticky="nw")
            return

        # Top toolbar
        tb = ctk.CTkFrame(self, fg_color="transparent")
        tb.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        ctk.CTkButton(tb, text="＋ Aggiungi", width=100, height=28,
                      command=self._add_files).pack(side="left", padx=(0, 4))
        ctk.CTkButton(tb, text="Rimuovi", width=80, height=28,
                      **_BTN_DARK, command=self._remove_sel).pack(side="left", padx=2)
        ctk.CTkButton(tb, text="Pulisci lista", width=90, height=28,
                      **_BTN_DARK, command=self._clear_list).pack(side="left", padx=2)

        # Body
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 0))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(0, weight=1)

        # Left — file list
        left = ctk.CTkFrame(body, fg_color=("#111", "#111"), corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self._list_sf = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._list_sf.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._empty_lbl = ctk.CTkLabel(
            self._list_sf,
            text="Nessun file\n\nclicca ＋ Aggiungi",
            text_color="#555", font=ctk.CTkFont(size=11))
        self._empty_lbl.pack(expand=True, pady=20)

        # Right — metadata tree
        self._meta_sf = ctk.CTkScrollableFrame(
            body, fg_color=("#111", "#111"), corner_radius=10)
        self._meta_sf.grid(row=0, column=1, sticky="nsew")
        self._meta_sf.grid_columnconfigure(1, weight=1)

        self._meta_placeholder = ctk.CTkLabel(
            self._meta_sf,
            text="Seleziona un file dalla lista\nper vedere tutti i suoi metadati.",
            text_color="#444", font=ctk.CTkFont(size=12))
        self._meta_placeholder.grid(row=0, column=0, columnspan=3,
                                     padx=20, pady=40)

        # Bottom bar
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 0))
        bot.grid_columnconfigure(0, weight=1)

        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")

        self._btn_analyze = ctk.CTkButton(
            bot, text="🔍 Analizza", width=105, height=36,
            font=ctk.CTkFont(size=11, weight="bold"),
            state="disabled", **_BTN_DARK, command=self._analyze)
        self._btn_analyze.grid(row=0, column=1, padx=(8, 0))

        self._btn_wipe = ctk.CTkButton(
            bot, text="🗑 Wipe completo", width=125, height=36,
            font=ctk.CTkFont(size=11, weight="bold"),
            state="disabled",
            fg_color="#7a1c1c", hover_color="#9a2c2c",
            command=self._wipe)
        self._btn_wipe.grid(row=0, column=2, padx=(6, 0))

        self._btn_apply_all = ctk.CTkButton(
            bot, text="↕ Applica a tutti", width=125, height=36,
            font=ctk.CTkFont(size=11, weight="bold"),
            state="disabled", **_BTN_DARK, command=self._apply_all)
        self._btn_apply_all.grid(row=0, column=3, padx=(6, 0))

        self._btn_save = ctk.CTkButton(
            bot, text="💾 Salva modifiche", width=135, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled", command=self._save)
        self._btn_save.grid(row=0, column=4, padx=(6, 0))

    # ── File list ──────────────────────────────────────────────────────────

    def _add_files(self) -> None:
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="Seleziona file audio",
            filetypes=[
                ("Audio", " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))),
                ("Tutti i file", "*.*"),
            ])
        existing = set(self._files)
        for p in paths:
            path = Path(p)
            if path not in existing:
                self._files.append(path)
                self._add_list_row(path)
                existing.add(path)
        self._refresh_empty()

    def _add_list_row(self, path: Path) -> None:
        idx = len(self._rows)
        row = ctk.CTkFrame(self._list_sf, fg_color="#222", corner_radius=6)
        row.pack(fill="x", pady=2)
        lbl = ctk.CTkLabel(row, text=path.name, anchor="w",
                           font=ctk.CTkFont(size=11))
        lbl.pack(side="left", padx=8, pady=6, fill="x", expand=True)
        row.bind("<Button-1>", lambda _, i=idx: self._select(i))
        lbl.bind("<Button-1>", lambda _, i=idx: self._select(i))
        self._rows.append(row)

    def _select(self, idx: int) -> None:
        if idx >= len(self._files):
            return
        if self._sel_idx is not None and self._sel_idx < len(self._rows):
            self._rows[self._sel_idx].configure(fg_color="#222")
        self._sel_idx = idx
        self._rows[idx].configure(fg_color="#1a3a5c")
        self._status.busy(f"Caricamento metadati: {self._files[idx].name}…")
        threading.Thread(target=self._load_meta_thread,
                         args=(self._files[idx],), daemon=True).start()

    def _load_meta_thread(self, path: Path) -> None:
        fields = self._engine.deep_read_tags(path)
        self.after(0, self._render_metadata, fields, path)

    def _remove_sel(self) -> None:
        if self._sel_idx is None:
            return
        self._rows[self._sel_idx].destroy()
        self._rows.pop(self._sel_idx)
        self._files.pop(self._sel_idx)
        self._sel_idx = None
        self._set_buttons(False)
        self._clear_meta_panel()
        self._refresh_empty()

    def _clear_list(self) -> None:
        for r in self._rows:
            r.destroy()
        self._rows.clear()
        self._files.clear()
        self._sel_idx = None
        self._set_buttons(False)
        self._clear_meta_panel()
        self._refresh_empty()

    def _refresh_empty(self) -> None:
        if self._files:
            self._empty_lbl.pack_forget()
        else:
            self._empty_lbl.pack(expand=True, pady=20)

    def _set_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self._btn_save, self._btn_wipe,
                    self._btn_analyze, self._btn_apply_all):
            btn.configure(state=state)
        if enabled and len(self._files) < 2:
            self._btn_apply_all.configure(state="disabled")

    # ── Metadata tree ──────────────────────────────────────────────────────

    def _clear_meta_panel(self) -> None:
        for widget in self._meta_sf.winfo_children():
            widget.destroy()
        self._field_entries.clear()
        self._field_rows.clear()
        self._pending_delete.clear()
        self._meta_placeholder = ctk.CTkLabel(
            self._meta_sf,
            text="Seleziona un file dalla lista\nper vedere tutti i suoi metadati.",
            text_color="#444", font=ctk.CTkFont(size=12))
        self._meta_placeholder.grid(row=0, column=0, columnspan=3,
                                     padx=20, pady=40)

    def _render_metadata(self, fields: list[dict], path: Path) -> None:
        # Destroy old content
        for widget in self._meta_sf.winfo_children():
            widget.destroy()
        self._field_entries.clear()
        self._field_rows.clear()
        self._pending_delete.clear()

        if not fields:
            ctk.CTkLabel(self._meta_sf,
                         text="Nessun metadato trovato.",
                         text_color="#555").grid(
                row=0, column=0, columnspan=3, pady=20)
            self._set_buttons(True)
            self._status.info(f"Nessun metadato: {path.name}")
            return

        # Group by category
        grouped: dict[str, list[dict]] = {c: [] for c in _CAT_ORDER}
        for f in fields:
            grouped.setdefault(f["category"], []).append(f)

        grid_row = 0
        self._meta_sf.grid_columnconfigure(1, weight=1)

        for cat in _CAT_ORDER:
            cat_fields = grouped.get(cat, [])
            if not cat_fields:
                continue

            label_text, label_color = _CAT_LABELS.get(
                cat, (cat.upper(), "#aaaaaa"))

            # Category header
            hdr = ctk.CTkLabel(
                self._meta_sf, text=f"  {label_text}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=label_color,
                anchor="w", fg_color="#1a1a1a", corner_radius=4)
            hdr.grid(row=grid_row, column=0, columnspan=3,
                     sticky="ew", padx=6, pady=(10, 2))
            grid_row += 1

            for f in cat_fields:
                grid_row = self._add_meta_row(f, grid_row)

        self._set_buttons(True)
        n = len(fields)
        self._status.ok(
            f"{path.name}  ·  {n} campo{'i' if n != 1 else ''} trovato{'i' if n != 1 else ''}")

    def _add_meta_row(self, f: dict, grid_row: int) -> int:
        raw_key  = f["raw_key"]
        editable = f["editable"]
        deletable = f["deletable"]
        warning  = f.get("warning", "")

        row = ctk.CTkFrame(self._meta_sf, fg_color="transparent")
        row.grid(row=grid_row, column=0, columnspan=3,
                 sticky="ew", padx=6, pady=1)
        row.grid_columnconfigure(1, weight=1)
        self._field_rows[raw_key] = row

        # Warning indicator
        if warning:
            ctk.CTkLabel(row, text="⚠",
                         text_color="#e8a020" if "storico" not in warning.lower()
                         else "#e04040",
                         font=ctk.CTkFont(size=11),
                         width=20).grid(row=0, column=0, padx=(2, 0))
        else:
            ctk.CTkLabel(row, text="", width=20).grid(row=0, column=0)

        # Field name
        name_lbl = ctk.CTkLabel(
            row, text=f["display_name"],
            anchor="w", width=180,
            font=ctk.CTkFont(size=11),
            text_color="#cccccc" if f["category"] == "info" else "#ffffff")
        name_lbl.grid(row=0, column=1, sticky="w", padx=(4, 8))

        # Value — editable Entry or read-only Label
        if editable:
            entry = ctk.CTkEntry(
                row, font=ctk.CTkFont(size=11),
                placeholder_text=f["display_name"])
            entry.insert(0, f["value"])
            entry.grid(row=0, column=2, sticky="ew", padx=(0, 4), pady=2)
            self._field_entries[raw_key] = entry
        else:
            ctk.CTkLabel(
                row, text=f["value"] or "—",
                anchor="w", font=ctk.CTkFont(size=10),
                text_color="#888888", wraplength=300, justify="left",
            ).grid(row=0, column=2, sticky="ew", padx=(0, 4), pady=2)

        # Delete button
        if deletable:
            ctk.CTkButton(
                row, text="✕", width=28, height=26,
                fg_color="#3a1a1a", hover_color="#6a2a2a",
                font=ctk.CTkFont(size=11),
                command=lambda rk=raw_key, r=row: self._mark_delete(rk, r),
            ).grid(row=0, column=3, padx=(2, 4))
        else:
            ctk.CTkLabel(row, text="", width=32).grid(row=0, column=3)

        # Tooltip — show warning on hover
        if warning:
            name_lbl.bind("<Enter>", lambda _, w=warning: self._status.info(f"⚠ {w}"))
            name_lbl.bind("<Leave>", lambda _: None)

        return grid_row + 1

    def _mark_delete(self, raw_key: str, row_frame: ctk.CTkFrame) -> None:
        self._pending_delete.add(raw_key)
        self._field_entries.pop(raw_key, None)
        row_frame.configure(fg_color="#3a0000")
        for w in row_frame.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.configure(
                    text="↩", fg_color="#1a3a1a", hover_color="#2a5a2a",
                    command=lambda rk=raw_key, r=row_frame: self._unmark_delete(rk, r))
                break

    def _unmark_delete(self, raw_key: str, row_frame: ctk.CTkFrame) -> None:
        self._pending_delete.discard(raw_key)
        row_frame.configure(fg_color="transparent")
        # Restore delete button
        for w in row_frame.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.configure(
                    text="✕", fg_color="#3a1a1a", hover_color="#6a2a2a",
                    command=lambda rk=raw_key, r=row_frame: self._mark_delete(rk, r))
                break

    # ── Actions ────────────────────────────────────────────────────────────

    def _save(self) -> None:
        if self._sel_idx is None:
            return
        path    = self._files[self._sel_idx]
        changes = {rk: e.get().strip()
                   for rk, e in self._field_entries.items()
                   if not rk.startswith("_info_")}
        deletions = set(self._pending_delete)
        self._set_buttons(False)
        self._status.busy("Salvataggio…")
        threading.Thread(
            target=self._worker_save,
            args=([path], changes, deletions), daemon=True).start()

    def _apply_all(self) -> None:
        if not self._files:
            return
        changes   = {rk: e.get().strip()
                     for rk, e in self._field_entries.items()
                     if not rk.startswith("_info_")}
        deletions = set(self._pending_delete)
        self._set_buttons(False)
        self._status.busy(f"Applicazione a {len(self._files)} file…")
        threading.Thread(
            target=self._worker_save,
            args=(list(self._files), changes, deletions), daemon=True).start()

    def _worker_save(self, paths: list[Path],
                     changes: dict, deletions: set) -> None:
        ok, errors = 0, []
        for path in paths:
            r = self._engine.save_meta_changes(path, changes, deletions)
            if r.success:
                ok += 1
            else:
                errors.append(f"{path.name}: {r.error}")
        if errors:
            self.after(0, self._status.err,
                       f"{ok}/{len(paths)} salvati — {errors[0]}")
        else:
            self.after(0, self._status.ok,
                       f"Salvati {ok} file — modifiche applicate")
        self.after(0, self._set_buttons, True)

    def _wipe(self) -> None:
        if self._sel_idx is None:
            return
        path = self._files[self._sel_idx]
        self._set_buttons(False)
        self._status.busy(f"Wipe completo: {path.name}…")
        threading.Thread(target=self._worker_wipe,
                         args=(path,), daemon=True).start()

    def _worker_wipe(self, path: Path) -> None:
        r = self._engine.forensic_wipe(path)
        if r.success:
            self.after(0, self._status.ok,
                       f"Wipe completato: {path.name}  —  tutti i metadati rimossi")
            # Reload the now-empty metadata view
            self.after(100, lambda: self._select(self._sel_idx))
        else:
            self.after(0, self._status.err, r.error)
            self.after(0, self._set_buttons, True)

    def _analyze(self) -> None:
        if self._sel_idx is None:
            return
        path = self._files[self._sel_idx]
        self._btn_analyze.configure(state="disabled")
        self._status.busy(f"Analisi: {path.name}…")
        threading.Thread(target=self._worker_analyze,
                         args=(path,), daemon=True).start()

    def _worker_analyze(self, path: Path) -> None:
        report = self._engine.analyze_file(path)
        # Show results in a floating label above the list
        lines = []
        lines.append("✅  FILE SICURO" if report["safe"]
                     else f"⚠   {len(report['issues'])} PROBLEMA/I RILEVATO/I")
        if report["issues"]:
            lines.append("")
            for issue in report["issues"]:
                lines.append(f"  ✗  {issue}")
        lines.append("")
        for detail in report["details"]:
            lines.append(f"  ✓  {detail}")
        text = "\n".join(lines)
        self.after(0, self._show_analysis, text, report["safe"])
        self.after(0, self._btn_analyze.configure, {"state": "normal"})

    def _show_analysis(self, text: str, safe: bool) -> None:
        # Show in a simple popup textbox window
        win = ctk.CTkToplevel(self)
        win.title("Risultato analisi")
        win.geometry("520x340")
        win.resizable(False, False)
        win.grab_set()
        color = "#1a3a1a" if safe else "#3a1a1a"
        win.configure(fg_color=color)
        box = ctk.CTkTextbox(win, font=ctk.CTkFont(family="Courier", size=11),
                             fg_color="#0d0d0d")
        box.pack(fill="both", expand=True, padx=12, pady=(12, 4))
        box.insert("end", text)
        box.configure(state="disabled")
        ctk.CTkButton(win, text="Chiudi", command=win.destroy,
                      width=100).pack(pady=(4, 12))
        if safe:
            self._status.ok("Analisi completata — nessun problema rilevato")
        else:
            self._status.err(
                f"Analisi: {text.count('✗')} problema/i rilevato/i")
