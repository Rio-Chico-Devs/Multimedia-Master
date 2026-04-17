"""
Metadata Tab — deep metadata inspector, editor and forensic wipe.

Features:
  • Multi-file list — click a file to load ALL metadata fields
  • Deep reading: ID3v1+v2, LAME/Xing stream header, MP4 atoms,
    Vorbis keys, FLAC vendor string — everything mutagen+binary can find
  • Provenance analysis: score + signals (⚠ coexisting ID3v1+v2,
    TDTG tagging timestamp, encoder fingerprints, iTunes atoms, …)
  • Album art thumbnail preview
  • Inline editing of every text field; ✕ per-field delete (undoable)
  • 'Salva modifiche'   — write changes to selected file
  • 'Applica a tutti'   — push same fields to every file in list
  • 'Wipe selezionato'  — forensic wipe on current file
  • 'Wipe tutti'        — forensic wipe on every file in list
  • 'Copia tag'         — copy all editable fields from selected file
                          and paste onto every other file in list
  • 'Export report'     — save TXT or JSON report for selected file
  • 'Analizza'          — health-check popup
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageTk

from common.ui.widgets import SectionLabel, Separator, StatusBar
from core.audio_engine import AudioEngine
from core.dependencies import DepStatus
from core.formats import AUDIO_EXTS


# ── Category config ────────────────────────────────────────────────────────────
_CAT_ORDER  = ["standard", "technical", "history", "hidden", "custom", "art", "info"]
_CAT_LABELS = {
    "standard":  ("Tag standard",                      "#ffffff"),
    "technical": ("Tecnici",                           "#aaaaaa"),
    "history":   ("⚠  Storico / Provenienza",          "#e8a020"),
    "hidden":    ("⚠  Dati nascosti / privati",        "#e04040"),
    "custom":    ("Tag personalizzati",                "#aaaaff"),
    "art":       ("Immagini incorporate",              "#aaaaaa"),
    "info":      ("Informazioni file (sola lettura)",  "#666666"),
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
        self._field_entries:  dict[str, ctk.CTkEntry] = {}
        self._pending_delete: set[str] = set()
        self._field_rows:     dict[str, ctk.CTkFrame] = {}
        self._art_photo: ImageTk.PhotoImage | None = None
        self._build()

    # ── Build skeleton ─────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        if not self._deps.mutagen:
            ctk.CTkLabel(
                self,
                text="⚠  Questa funzione richiede mutagen.\n\n"
                     "Installa con:  pip install mutagen\n\n"
                     "Poi riavvia Multimedia Master.",
                font=ctk.CTkFont(size=12), text_color="#f44336", justify="left",
            ).grid(row=0, column=0, padx=40, pady=40, sticky="nw")
            return

        # Toolbar
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
            self._list_sf, text="Nessun file\n\nclicca ＋ Aggiungi",
            text_color="#555", font=ctk.CTkFont(size=11))
        self._empty_lbl.pack(expand=True, pady=20)

        # Right — metadata tree
        self._meta_sf = ctk.CTkScrollableFrame(
            body, fg_color=("#111", "#111"), corner_radius=10)
        self._meta_sf.grid(row=0, column=1, sticky="nsew")
        self._meta_sf.grid_columnconfigure(2, weight=1)
        self._placeholder = ctk.CTkLabel(
            self._meta_sf,
            text="Seleziona un file dalla lista\nper vedere tutti i suoi metadati.",
            text_color="#444", font=ctk.CTkFont(size=12))
        self._placeholder.grid(row=0, column=0, columnspan=4, padx=20, pady=40)

        # Bottom bar
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 0))
        bot.grid_columnconfigure(0, weight=1)

        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")

        btn_cfg = [
            ("_btn_analyze",    "🔍 Analizza",        110, _BTN_DARK,                          self._analyze),
            ("_btn_export",     "📄 Export report",   120, _BTN_DARK,                          self._export),
            ("_btn_copy",       "⎘ Copia tag",        100, _BTN_DARK,                          self._copy_tags),
            ("_btn_wipe_all",   "🗑 Wipe tutti",       100, {"fg_color":"#7a1c1c","hover_color":"#9a2c2c"}, self._wipe_all),
            ("_btn_wipe",       "🗑 Wipe sel.",         90, {"fg_color":"#7a1c1c","hover_color":"#9a2c2c"}, self._wipe),
            ("_btn_apply_all",  "↕ Applica tutti",    115, _BTN_DARK,                          self._apply_all),
            ("_btn_save",       "💾 Salva",             80, {},                                 self._save),
        ]
        for col, (attr, text, w, kw_extra, cmd) in enumerate(btn_cfg, start=1):
            btn = ctk.CTkButton(
                bot, text=text, width=w, height=36,
                font=ctk.CTkFont(size=11, weight="bold"),
                state="disabled", command=cmd, **kw_extra)
            btn.grid(row=0, column=col, padx=(4 if col > 1 else 8, 0))
            setattr(self, attr, btn)

    # ── File list ──────────────────────────────────────────────────────────

    def _add_files(self) -> None:
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="Seleziona file audio",
            filetypes=[("Audio", " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))),
                       ("Tutti i file", "*.*")])
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
        for w in (row, lbl):
            w.bind("<Button-1>", lambda _, i=idx: self._select(i))
        self._rows.append(row)

    def _select(self, idx: int) -> None:
        if idx >= len(self._files):
            return
        if self._sel_idx is not None and self._sel_idx < len(self._rows):
            self._rows[self._sel_idx].configure(fg_color="#222")
        self._sel_idx = idx
        self._rows[idx].configure(fg_color="#1a3a5c")
        self._status.busy(f"Caricamento: {self._files[idx].name}…")
        threading.Thread(target=self._load_thread,
                         args=(self._files[idx],), daemon=True).start()

    def _load_thread(self, path: Path) -> None:
        fields     = self._engine.deep_read_tags(path)
        provenance = self._engine.compute_provenance(path, fields)
        art_bytes  = self._engine.get_album_art(path)
        self.after(0, self._render, fields, provenance, art_bytes, path)

    def _remove_sel(self) -> None:
        if self._sel_idx is None:
            return
        self._rows[self._sel_idx].destroy()
        self._rows.pop(self._sel_idx)
        self._files.pop(self._sel_idx)
        self._sel_idx = None
        self._set_buttons(False)
        self._clear_panel()
        self._refresh_empty()

    def _clear_list(self) -> None:
        for r in self._rows:
            r.destroy()
        self._rows.clear(); self._files.clear()
        self._sel_idx = None
        self._set_buttons(False)
        self._clear_panel()
        self._refresh_empty()

    def _refresh_empty(self) -> None:
        if self._files:
            self._empty_lbl.pack_forget()
        else:
            self._empty_lbl.pack(expand=True, pady=20)

    def _set_buttons(self, on: bool) -> None:
        state = "normal" if on else "disabled"
        for attr in ("_btn_save", "_btn_wipe", "_btn_wipe_all",
                     "_btn_analyze", "_btn_export", "_btn_copy", "_btn_apply_all"):
            getattr(self, attr).configure(state=state)
        if on and len(self._files) < 2:
            self._btn_apply_all.configure(state="disabled")
            self._btn_wipe_all.configure(state="disabled")
            self._btn_copy.configure(state="disabled")

    # ── Metadata tree ──────────────────────────────────────────────────────

    def _clear_panel(self) -> None:
        for w in self._meta_sf.winfo_children():
            w.destroy()
        self._field_entries.clear()
        self._field_rows.clear()
        self._pending_delete.clear()
        self._art_photo = None
        self._placeholder = ctk.CTkLabel(
            self._meta_sf,
            text="Seleziona un file dalla lista\nper vedere tutti i suoi metadati.",
            text_color="#444", font=ctk.CTkFont(size=12))
        self._placeholder.grid(row=0, column=0, columnspan=4, padx=20, pady=40)

    def _render(self, fields: list[dict], provenance: dict,
                art_bytes: bytes | None, path: Path) -> None:
        for w in self._meta_sf.winfo_children():
            w.destroy()
        self._field_entries.clear()
        self._field_rows.clear()
        self._pending_delete.clear()
        self._art_photo = None

        self._meta_sf.grid_columnconfigure(0, weight=0, minsize=22)
        self._meta_sf.grid_columnconfigure(1, weight=0, minsize=190)
        self._meta_sf.grid_columnconfigure(2, weight=1)
        self._meta_sf.grid_columnconfigure(3, weight=0, minsize=36)

        grid_row = 0

        # ── Provenance panel ──────────────────────────────────────────────
        prov_frame = ctk.CTkFrame(
            self._meta_sf,
            fg_color="#1a1400" if provenance["score"] > 0 else "#001a00",
            corner_radius=8)
        prov_frame.grid(row=grid_row, column=0, columnspan=4,
                        sticky="ew", padx=6, pady=(8, 4))
        prov_frame.grid_columnconfigure(0, weight=1)
        grid_row += 1

        ctk.CTkLabel(prov_frame, text=provenance["verdict"],
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew",
                                      padx=10, pady=(6, 2))

        score_bar = ctk.CTkProgressBar(prov_frame, height=6, corner_radius=3,
                                        progress_color=(
                                            "#4caf50" if provenance["score"] < 20
                                            else "#ff9800" if provenance["score"] < 50
                                            else "#f44336"))
        score_bar.set(provenance["score"] / 100)
        score_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))

        ctk.CTkLabel(prov_frame,
                     text=f"Score: {provenance['score']}/100  ·  "
                          f"SHA-256: {provenance['hash'][:16]}…  ·  "
                          f"Modificato: {provenance['fs_modified']}",
                     text_color="#888", font=ctk.CTkFont(size=10),
                     anchor="w").grid(row=2, column=0, sticky="ew",
                                      padx=10, pady=(0, 2))

        if provenance["signals"]:
            sig_text = "\n".join(f"  • {s}" for s in provenance["signals"])
            ctk.CTkLabel(prov_frame, text=sig_text,
                         text_color="#ccaa44", font=ctk.CTkFont(size=10),
                         anchor="w", justify="left").grid(
                row=3, column=0, sticky="ew", padx=10, pady=(0, 6))

        # ── Album art preview ─────────────────────────────────────────────
        if art_bytes:
            try:
                from io import BytesIO
                img = Image.open(BytesIO(art_bytes)).convert("RGB")
                img.thumbnail((96, 96))
                self._art_photo = ImageTk.PhotoImage(img)
                art_lbl = ctk.CTkLabel(
                    self._meta_sf, image=self._art_photo, text="",
                    width=96, height=96, fg_color="#1a1a1a", corner_radius=6)
                art_lbl.grid(row=grid_row, column=0, columnspan=4,
                             padx=6, pady=(4, 0), sticky="w")
                grid_row += 1
            except Exception:
                pass

        # ── Fields grouped by category ────────────────────────────────────
        grouped: dict[str, list[dict]] = {c: [] for c in _CAT_ORDER}
        for f in fields:
            grouped.setdefault(f["category"], []).append(f)

        for cat in _CAT_ORDER:
            cat_fields = grouped.get(cat, [])
            if not cat_fields:
                continue
            lbl_text, lbl_color = _CAT_LABELS.get(cat, (cat.upper(), "#aaa"))
            hdr = ctk.CTkLabel(
                self._meta_sf, text=f"  {lbl_text}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=lbl_color, anchor="w",
                fg_color="#1a1a1a", corner_radius=4)
            hdr.grid(row=grid_row, column=0, columnspan=4,
                     sticky="ew", padx=6, pady=(10, 2))
            grid_row += 1
            for f in cat_fields:
                grid_row = self._add_field_row(f, grid_row)

        self._set_buttons(True)
        n = len(fields)
        self._status.ok(f"{path.name}  ·  {n} campi  ·  "
                        f"score {provenance['score']}/100")

    def _add_field_row(self, f: dict, grid_row: int) -> int:
        raw_key   = f["raw_key"]
        editable  = f["editable"]
        deletable = f["deletable"]
        warning   = f.get("warning", "")

        row = ctk.CTkFrame(self._meta_sf, fg_color="transparent")
        row.grid(row=grid_row, column=0, columnspan=4,
                 sticky="ew", padx=6, pady=1)
        row.grid_columnconfigure(2, weight=1)
        self._field_rows[raw_key] = row

        # Col 0 — warning indicator
        warn_lbl = ctk.CTkLabel(
            row, text="⚠" if warning else "",
            text_color="#e8a020", font=ctk.CTkFont(size=10), width=20)
        warn_lbl.grid(row=0, column=0, padx=(2, 0))

        # Col 1 — field name
        name_lbl = ctk.CTkLabel(
            row, text=f["display_name"], anchor="w", width=185,
            font=ctk.CTkFont(size=11),
            text_color="#cccccc" if f["category"] == "info" else "#ffffff")
        name_lbl.grid(row=0, column=1, sticky="w", padx=(4, 8))

        # Col 2 — value
        if editable:
            entry = ctk.CTkEntry(row, font=ctk.CTkFont(size=11),
                                 placeholder_text=f["display_name"])
            entry.insert(0, f["value"])
            entry.grid(row=0, column=2, sticky="ew", padx=(0, 4), pady=2)
            self._field_entries[raw_key] = entry
        else:
            val_text = f["value"] if len(f["value"]) <= 90 else f["value"][:87] + "…"
            ctk.CTkLabel(
                row, text=val_text or "—", anchor="w",
                font=ctk.CTkFont(size=10), text_color="#888888",
                wraplength=320, justify="left",
            ).grid(row=0, column=2, sticky="ew", padx=(0, 4), pady=2)

        # Col 3 — delete button
        if deletable:
            ctk.CTkButton(
                row, text="✕", width=28, height=26,
                fg_color="#3a1a1a", hover_color="#6a2a2a",
                font=ctk.CTkFont(size=11),
                command=lambda rk=raw_key, r=row: self._mark_delete(rk, r),
            ).grid(row=0, column=3, padx=(2, 4))
        else:
            ctk.CTkLabel(row, text="", width=32).grid(row=0, column=3)

        # Warning tooltip on hover
        if warning:
            for w_widget in (warn_lbl, name_lbl):
                w_widget.bind("<Enter>",
                              lambda _, ww=warning: self._status.info(f"⚠ {ww}"))

        return grid_row + 1

    def _mark_delete(self, raw_key: str, row_frame: ctk.CTkFrame) -> None:
        self._pending_delete.add(raw_key)
        self._field_entries.pop(raw_key, None)
        row_frame.configure(fg_color="#3a0000")
        for w in row_frame.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.configure(text="↩", fg_color="#1a3a1a", hover_color="#2a5a2a",
                            command=lambda rk=raw_key, r=row_frame:
                                self._unmark_delete(rk, r))
                break

    def _unmark_delete(self, raw_key: str, row_frame: ctk.CTkFrame) -> None:
        self._pending_delete.discard(raw_key)
        row_frame.configure(fg_color="transparent")
        for w in row_frame.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.configure(text="✕", fg_color="#3a1a1a", hover_color="#6a2a2a",
                            command=lambda rk=raw_key, r=row_frame:
                                self._mark_delete(rk, r))
                break

    # ── Actions ────────────────────────────────────────────────────────────

    def _current_changes(self) -> dict[str, str]:
        return {rk: e.get().strip()
                for rk, e in self._field_entries.items()
                if not rk.startswith("_info_") and not rk.startswith("_fs_")
                and not rk.startswith("_sha") and not rk.startswith("_xing")
                and not rk.startswith("_lame") and not rk.startswith("_id3v")}

    def _save(self) -> None:
        if self._sel_idx is None:
            return
        path      = self._files[self._sel_idx]
        changes   = self._current_changes()
        deletions = set(self._pending_delete)
        self._set_buttons(False)
        self._status.busy("Salvataggio…")
        threading.Thread(
            target=self._worker_save,
            args=([path], changes, deletions), daemon=True).start()

    def _apply_all(self) -> None:
        changes   = self._current_changes()
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
        msg = f"Salvati {ok}/{len(paths)} file"
        if errors:
            self.after(0, self._status.err, msg + f" — {errors[0]}")
        else:
            self.after(0, self._status.ok, msg)
        self.after(0, self._set_buttons, True)

    def _wipe(self) -> None:
        if self._sel_idx is None:
            return
        path = self._files[self._sel_idx]
        self._set_buttons(False)
        self._status.busy(f"Wipe: {path.name}…")
        threading.Thread(target=self._worker_wipe,
                         args=([path],), daemon=True).start()

    def _wipe_all(self) -> None:
        if not self._files:
            return
        self._set_buttons(False)
        self._status.busy(f"Wipe su {len(self._files)} file…")
        threading.Thread(target=self._worker_wipe,
                         args=(list(self._files),), daemon=True).start()

    def _worker_wipe(self, paths: list[Path]) -> None:
        ok, errors = 0, []
        for path in paths:
            r = self._engine.forensic_wipe(path)
            if r.success:
                ok += 1
            else:
                errors.append(f"{path.name}: {r.error}")
        msg = f"Wipe completato su {ok}/{len(paths)} file"
        if errors:
            self.after(0, self._status.err, msg + f" — {errors[0]}")
        else:
            self.after(0, self._status.ok, msg)
        # Reload selected file view
        if self._sel_idx is not None:
            self.after(100, lambda: self._select(self._sel_idx))
        else:
            self.after(0, self._set_buttons, True)

    def _copy_tags(self) -> None:
        """Copy editable fields from selected file → all others in list."""
        if self._sel_idx is None or len(self._files) < 2:
            return
        changes   = self._current_changes()
        deletions = set(self._pending_delete)
        targets   = [p for i, p in enumerate(self._files) if i != self._sel_idx]
        self._set_buttons(False)
        self._status.busy(f"Copia tag su {len(targets)} file…")
        threading.Thread(
            target=self._worker_save,
            args=(targets, changes, deletions), daemon=True).start()

    def _export(self) -> None:
        if self._sel_idx is None:
            return
        from tkinter import filedialog
        path = self._files[self._sel_idx]
        out = filedialog.asksaveasfilename(
            title="Salva report metadati",
            defaultextension=".txt",
            initialfile=path.stem + "_metadata_report",
            filetypes=[("Testo", "*.txt"), ("JSON", "*.json")])
        if not out:
            return
        self._status.busy("Export in corso…")
        threading.Thread(target=self._worker_export,
                         args=(path, Path(out)), daemon=True).start()

    def _worker_export(self, path: Path, out: Path) -> None:
        fields     = self._engine.deep_read_tags(path)
        provenance = self._engine.compute_provenance(path, fields)
        r = self._engine.export_report(path, fields, provenance, out)
        if r.success:
            self.after(0, self._status.ok, f"Report salvato: {out.name}")
        else:
            self.after(0, self._status.err, r.error)

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
        lines = [
            "✅  FILE SICURO" if report["safe"]
            else f"⚠   {len(report['issues'])} PROBLEMA/I",
            "",
        ]
        if report["issues"]:
            lines.append("── Problemi ──")
            lines += [f"  ✗  {i}" for i in report["issues"]]
            lines.append("")
        lines.append("── Dettagli ──")
        lines += [f"  ✓  {d}" for d in report["details"]]
        text = "\n".join(lines)
        self.after(0, self._show_analyze_popup, text, report["safe"])
        self.after(0, lambda: self._btn_analyze.configure(state="normal"))

    def _show_analyze_popup(self, text: str, safe: bool) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Analisi file")
        win.geometry("520x340")
        win.resizable(False, False)
        win.grab_set()
        win.configure(fg_color="#1a3a1a" if safe else "#3a1a1a")
        box = ctk.CTkTextbox(win, font=ctk.CTkFont(family="Courier", size=11),
                             fg_color="#0d0d0d")
        box.pack(fill="both", expand=True, padx=12, pady=(12, 4))
        box.insert("end", text)
        box.configure(state="disabled")
        ctk.CTkButton(win, text="Chiudi", command=win.destroy,
                      width=100).pack(pady=(4, 12))
        if safe:
            self._status.ok("Analisi: nessun problema rilevato")
        else:
            self._status.err(f"Analisi: {text.count('✗')} problema/i")
