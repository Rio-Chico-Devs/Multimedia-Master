"""
Batch rename dialog for the image converter queue.

Renames the queued files on disk using a template with three tokens:
    {name}  original filename without extension
    {n}     sequential counter (zero-padded to the chosen width)
    {ext}   original extension without the dot

A live preview shows every old → new mapping before anything touches the disk.
The rename itself is two-phase (everything → unique temp names, then temp →
final) so order swaps like A↔B can never clobber a file mid-operation. The
extension is always preserved from the original file.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from common.ui.geometry import fit_window


class BatchRenameDialog(ctk.CTkToplevel):

    def __init__(self, parent, paths: list[Path],
                 on_apply: Callable[[dict[Path, Path]], None]):
        super().__init__(parent)
        self.title("Rinomina batch")
        self._paths    = list(paths)
        self._on_apply = on_apply
        fit_window(self, 620, 560, 460, 380)
        self.transient(parent)
        self._build()
        self._refresh_preview()
        # Grab focus once the window is actually on screen.
        self.after(100, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
        except Exception:
            pass

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Controls
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 4))
        ctrl.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(ctrl, text="Modello", width=70, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, padx=(0, 8), pady=4)
        self._tpl_var = ctk.StringVar(value="{name}")
        tpl_entry = ctk.CTkEntry(ctrl, textvariable=self._tpl_var)
        tpl_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)
        self._tpl_var.trace_add("write", lambda *_: self._refresh_preview())

        ctk.CTkLabel(ctrl, text="Inizio", width=70, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=1, column=0, padx=(0, 8), pady=4)
        self._start_var = ctk.StringVar(value="1")
        start_entry = ctk.CTkEntry(ctrl, width=70, textvariable=self._start_var)
        start_entry.grid(row=1, column=1, sticky="w", pady=4)
        self._start_var.trace_add("write", lambda *_: self._refresh_preview())

        ctk.CTkLabel(ctrl, text="Cifre", anchor="e").grid(
            row=1, column=2, sticky="e", padx=(0, 4))
        self._digits_var = ctk.StringVar(value="3")
        ctk.CTkOptionMenu(ctrl, width=70, variable=self._digits_var,
                          values=["1", "2", "3", "4", "5"],
                          command=lambda _=None: self._refresh_preview()).grid(
            row=2, column=2, sticky="e", pady=4)

        ctk.CTkLabel(
            self,
            text="Token disponibili:  {name} = nome originale   ·   "
                 "{n} = numero progressivo   ·   {ext} = estensione",
            text_color="gray", font=ctk.CTkFont(size=10),
            anchor="w", justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 4))

        # Preview list
        self._preview = ctk.CTkScrollableFrame(self, label_text="Anteprima")
        self._preview.grid(row=2, column=0, sticky="nsew", padx=16, pady=4)
        self._preview.grid_columnconfigure(0, weight=1)

        # Bottom bar
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 16))
        bot.grid_columnconfigure(0, weight=1)
        self._warn_lbl = ctk.CTkLabel(bot, text="", text_color="#ff9800",
                                      anchor="w", font=ctk.CTkFont(size=11))
        self._warn_lbl.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(bot, text="Annulla", width=90, height=34,
                      fg_color="#2a2a2a", hover_color="#3a3a3a",
                      command=self.destroy).grid(row=0, column=1, padx=(8, 0))
        self._apply_btn = ctk.CTkButton(
            bot, text="✓  Applica", width=120, height=34,
            font=ctk.CTkFont(size=12, weight="bold"), command=self._apply)
        self._apply_btn.grid(row=0, column=2, padx=(8, 0))

    # ── Name computation ─────────────────────────────────────────────────────

    def _start(self) -> int:
        try:
            return int(self._start_var.get())
        except ValueError:
            return 1

    def _digits(self) -> int:
        try:
            return int(self._digits_var.get())
        except ValueError:
            return 3

    def _compute_plan(self) -> list[tuple[Path, Path]]:
        """Build the [(old, new)] plan, resolving collisions deterministically."""
        tpl    = self._tpl_var.get().strip() or "{name}"
        start  = self._start()
        digits = self._digits()
        plan: list[tuple[Path, Path]] = []
        used: set[str] = set()

        for i, old in enumerate(self._paths):
            stem = (tpl.replace("{name}", old.stem)
                       .replace("{n}", str(start + i).zfill(digits))
                       .replace("{ext}", old.suffix.lstrip(".")))
            stem = self._sanitize(stem) or old.stem
            candidate = stem + old.suffix
            # De-duplicate within the batch by appending _2, _3, …
            final = candidate
            n = 2
            while final.lower() in used:
                final = f"{stem}_{n}{old.suffix}"
                n += 1
            used.add(final.lower())
            plan.append((old, old.with_name(final)))
        return plan

    @staticmethod
    def _sanitize(name: str) -> str:
        bad = '<>:"/\\|?*'
        return "".join(c for c in name if c not in bad).strip()

    # ── Preview ──────────────────────────────────────────────────────────────

    def _refresh_preview(self) -> None:
        for child in self._preview.winfo_children():
            child.destroy()
        plan = self._compute_plan()
        clashes = 0
        for old, new in plan:
            # A clash with an existing unrelated file on disk is flagged.
            exists = new.exists() and new != old
            if exists:
                clashes += 1
            row = ctk.CTkFrame(self._preview, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=old.name, anchor="w", text_color="#888",
                         font=ctk.CTkFont(size=11)).pack(side="left")
            ctk.CTkLabel(row, text="  →  ", text_color="#555").pack(side="left")
            ctk.CTkLabel(
                row, text=new.name, anchor="w",
                text_color="#f44336" if exists else "#4caf50",
                font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")

        if clashes:
            self._warn_lbl.configure(
                text=f"⚠ {clashes} nome/i già esistono su disco — verranno saltati")
        else:
            self._warn_lbl.configure(text="")

    # ── Apply ──────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        plan = [(o, n) for o, n in self._compute_plan() if o != n]
        # Skip targets that already exist on disk and aren't part of the batch.
        batch_olds = {o for o, _ in plan}
        plan = [(o, n) for o, n in plan
                if not (n.exists() and n not in batch_olds)]
        if not plan:
            self.destroy()
            return

        # Phase 1 — move every source to a unique temp name in its own folder.
        temps: list[tuple[Path, Path, Path]] = []   # (original, temp, final)
        try:
            for old, new in plan:
                tmp = old.with_name(f".mmrename_{uuid.uuid4().hex}{old.suffix}")
                old.rename(tmp)
                temps.append((old, tmp, new))
            # Phase 2 — temp → final.
            mapping: dict[Path, Path] = {}
            for original, tmp, new in temps:
                tmp.rename(new)
                mapping[original] = new
        except Exception as exc:
            # Best-effort rollback of any temp files still pending.
            for original, tmp, _new in temps:
                if tmp.exists() and not original.exists():
                    try: tmp.rename(original)
                    except Exception: pass
            from tkinter import messagebox
            messagebox.showerror("Rinomina fallita",
                                 f"Errore durante la rinomina:\n{exc}")
            self.destroy()
            return

        self._on_apply(mapping)
        self.destroy()
