import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
from pathlib import Path
from PIL import Image
import os

# ── Tema ───────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Costanti ───────────────────────────────────────────────────────────────────
INPUT_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}

OUTPUT_FORMATS = ["WebP", "JPEG", "PNG", "TIFF", "BMP", "GIF"]

QUALITY_DEFAULTS = {
    "WebP": 85, "JPEG": 85, "PNG": 85, "TIFF": 90, "BMP": 100, "GIF": 80,
}

QUALITY_HINTS = {
    "WebP":  "Consigliato 85 · fino a -35% vs JPEG a parità di qualità",
    "JPEG":  "Consigliato 85 · progressivo, ottimizzato",
    "PNG":   "Lossless · qualità agisce sulla compressione",
    "TIFF":  "Consigliato 90 · ideale per archivio",
    "BMP":   "Nessuna compressione — qualità non applicabile",
    "GIF":   "Max 256 colori · per animazioni o grafica semplice",
}

EXT_MAP = {
    "WebP": ".webp", "JPEG": ".jpg", "PNG": ".png",
    "TIFF": ".tiff", "BMP": ".bmp", "GIF": ".gif",
}


# ── Riga file ──────────────────────────────────────────────────────────────────
class FileRow(ctk.CTkFrame):
    def __init__(self, parent, file_path: Path, on_remove, **kw):
        super().__init__(parent, corner_radius=8, **kw)
        self.file_path = file_path

        # Miniatura
        try:
            pil = Image.open(file_path)
            pil.thumbnail((48, 48), Image.LANCZOS)
            self._thumb = ctk.CTkImage(pil, size=(min(48, pil.width), min(48, pil.height)))
            ctk.CTkLabel(self, image=self._thumb, text="").pack(
                side="left", padx=(10, 6), pady=8)
        except Exception:
            ctk.CTkLabel(self, text="🖼", font=ctk.CTkFont(size=22), width=48).pack(
                side="left", padx=(10, 6), pady=8)

        # Info file
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(info, text=file_path.name, anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x")

        size_b = file_path.stat().st_size
        size_str = (f"{size_b/1024:.0f} KB" if size_b < 1_048_576
                    else f"{size_b/1_048_576:.2f} MB")
        ctk.CTkLabel(info,
                     text=f"{size_str}  ·  {file_path.suffix[1:].upper()}  ·  "
                          f"{self._get_dims(file_path)}",
                     anchor="w", text_color="gray",
                     font=ctk.CTkFont(size=11)).pack(fill="x")

        # Stato conversione
        self.status = ctk.CTkLabel(self, text="", width=80,
                                   font=ctk.CTkFont(size=12))
        self.status.pack(side="right", padx=6)

        # Pulsante rimuovi
        ctk.CTkButton(self, text="✕", width=30, height=30,
                      fg_color="transparent", hover_color="#3a3a3a",
                      command=lambda: on_remove(self)).pack(side="right", padx=(0, 8))

    @staticmethod
    def _get_dims(path: Path) -> str:
        try:
            w, h = Image.open(path).size
            return f"{w}×{h} px"
        except Exception:
            return ""

    def set_status(self, text: str, color: str = "gray"):
        self.status.configure(text=text, text_color=color)


# ── Applicazione principale ────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Multimedia Master  —  Convertitore Immagini")
        self.geometry("960x680")
        self.minsize(720, 520)

        self._file_rows: list[FileRow] = []
        self._output_dir: Path | None = None
        self._converting = False

        self._build_ui()

    # ── Costruzione UI ─────────────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self._build_left()
        self._build_right()

    def _build_left(self):
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        # ── Zona aggiungi file ─────────────────────────────────────────────────
        drop = ctk.CTkFrame(left, height=100, corner_radius=12,
                            border_width=2, border_color="#1f6aa5")
        drop.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        drop.grid_propagate(False)
        drop.grid_columnconfigure(0, weight=1)
        drop.grid_rowconfigure(0, weight=1)

        inner = ctk.CTkFrame(drop, fg_color="transparent")
        inner.grid(row=0, column=0)
        ctk.CTkLabel(inner, text="Aggiungi immagini da convertire",
                     font=ctk.CTkFont(size=14, weight="bold")).pack()
        ctk.CTkButton(inner, text="  Sfoglia file  ", width=140, height=34,
                      command=self._browse).pack(pady=(6, 0))

        # ── Lista file ─────────────────────────────────────────────────────────
        self._list_frame = ctk.CTkScrollableFrame(left, label_text="File in coda")
        self._list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        self._list_frame.grid_columnconfigure(0, weight=1)

        self._empty_lbl = ctk.CTkLabel(
            self._list_frame,
            text="Nessun file caricato.\nClicca 'Sfoglia file' per iniziare.",
            text_color="gray", justify="center",
        )
        self._empty_lbl.pack(pady=30)

        # ── Barra inferiore ────────────────────────────────────────────────────
        bar = ctk.CTkFrame(left, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 10))

        self._progress = ctk.CTkProgressBar(bar, height=8)
        self._progress.pack(fill="x", pady=(0, 8))
        self._progress.set(0)

        self._convert_btn = ctk.CTkButton(
            bar, text="▶  Converti tutto", height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_conversion,
        )
        self._convert_btn.pack(fill="x")

        self._status_lbl = ctk.CTkLabel(bar, text="", text_color="gray",
                                        font=ctk.CTkFont(size=11))
        self._status_lbl.pack(pady=(4, 0))

    def _build_right(self):
        right = ctk.CTkFrame(self, width=260)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        right.grid_propagate(False)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Impostazioni",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
            pady=(18, 10), padx=18)

        # ── Formato output ─────────────────────────────────────────────────────
        ctk.CTkLabel(right, text="Formato output", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
            fill="x", padx=18, pady=(6, 2))

        self._fmt_var = ctk.StringVar(value="WebP")
        ctk.CTkOptionMenu(right, values=OUTPUT_FORMATS,
                          variable=self._fmt_var,
                          command=self._on_format_change,
                          dynamic_resizing=False).pack(
            fill="x", padx=18, pady=(0, 4))

        # ── Qualità ────────────────────────────────────────────────────────────
        self._quality_lbl = ctk.CTkLabel(right, text="Qualità: 85", anchor="w",
                                         font=ctk.CTkFont(size=12, weight="bold"))
        self._quality_lbl.pack(fill="x", padx=18, pady=(10, 2))

        self._quality_slider = ctk.CTkSlider(
            right, from_=1, to=100, number_of_steps=99,
            command=self._on_quality_change,
        )
        self._quality_slider.set(85)
        self._quality_slider.pack(fill="x", padx=18)

        self._quality_hint = ctk.CTkLabel(
            right, text=QUALITY_HINTS["WebP"],
            text_color="gray", font=ctk.CTkFont(size=10),
            anchor="w", wraplength=220, justify="left",
        )
        self._quality_hint.pack(fill="x", padx=18, pady=(2, 10))

        self._sep(right)

        # ── Ridimensiona ───────────────────────────────────────────────────────
        ctk.CTkLabel(right, text="Ridimensiona  (opzionale)",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x", padx=18, pady=(10, 4))

        row = ctk.CTkFrame(right, fg_color="transparent")
        row.pack(fill="x", padx=18)
        row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(row, text="Larghezza px", anchor="w",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(row, text="Altezza px", anchor="w",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=1, sticky="w")

        self._w_entry = ctk.CTkEntry(row, placeholder_text="es. 1920")
        self._w_entry.grid(row=1, column=0, padx=(0, 4), pady=2, sticky="ew")
        self._h_entry = ctk.CTkEntry(row, placeholder_text="es. 1080")
        self._h_entry.grid(row=1, column=1, pady=2, sticky="ew")

        ctk.CTkLabel(right,
                     text="Mantiene proporzioni · non ingrandisce mai",
                     text_color="gray", font=ctk.CTkFont(size=10), anchor="w").pack(
            fill="x", padx=18, pady=(2, 6))

        self._sep(right)

        # ── Opzioni ────────────────────────────────────────────────────────────
        ctk.CTkLabel(right, text="Opzioni",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x", padx=18, pady=(10, 4))

        self._strip_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(right, text="Rimuovi metadati EXIF",
                        variable=self._strip_var).pack(
            fill="x", padx=18, pady=2)

        self._sep(right)

        # ── Cartella output ────────────────────────────────────────────────────
        ctk.CTkLabel(right, text="Cartella output",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w").pack(fill="x", padx=18, pady=(10, 2))

        self._outdir_lbl = ctk.CTkLabel(
            right, text="Stessa cartella dei file originali",
            text_color="gray", font=ctk.CTkFont(size=10),
            anchor="w", wraplength=220, justify="left",
        )
        self._outdir_lbl.pack(fill="x", padx=18, pady=(0, 4))

        ctk.CTkButton(right, text="Scegli cartella…", height=30,
                      command=self._choose_outdir).pack(
            fill="x", padx=18, pady=(0, 4))
        ctk.CTkButton(right, text="Ripristina cartella originale",
                      height=28, fg_color="transparent", border_width=1,
                      command=self._reset_outdir).pack(fill="x", padx=18)

    @staticmethod
    def _sep(parent):
        ctk.CTkFrame(parent, height=1, fg_color="#2a2a2a").pack(
            fill="x", padx=18, pady=4)

    # ── Callbacks UI ───────────────────────────────────────────────────────────
    def _on_format_change(self, fmt: str):
        q = QUALITY_DEFAULTS.get(fmt, 85)
        self._quality_slider.set(q)
        self._quality_lbl.configure(text=f"Qualità: {q}")
        self._quality_hint.configure(text=QUALITY_HINTS.get(fmt, ""))
        disabled = fmt in ("BMP", "GIF")
        state = "disabled" if disabled else "normal"
        self._quality_slider.configure(state=state)

    def _on_quality_change(self, val):
        self._quality_lbl.configure(text=f"Qualità: {int(val)}")

    def _browse(self):
        paths = filedialog.askopenfilenames(
            title="Seleziona immagini",
            filetypes=[
                ("Immagini supportate",
                 "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tiff *.tif"),
                ("Tutti i file", "*.*"),
            ],
        )
        for p in paths:
            self._add_file(Path(p))

    def _add_file(self, path: Path):
        if path.suffix.lower() not in INPUT_EXTS:
            return
        if any(r.file_path == path for r in self._file_rows):
            return
        if self._empty_lbl.winfo_ismapped():
            self._empty_lbl.pack_forget()

        row = FileRow(self._list_frame, path, self._remove_file)
        row.pack(fill="x", pady=3, padx=4)
        self._file_rows.append(row)
        self._refresh_status()

    def _remove_file(self, row: FileRow):
        row.destroy()
        self._file_rows.remove(row)
        if not self._file_rows:
            self._empty_lbl.pack(pady=30)
        self._refresh_status()

    def _refresh_status(self):
        n = len(self._file_rows)
        self._status_lbl.configure(
            text=f"{n} immagine{'i' if n != 1 else 'e'} in coda" if n else ""
        )

    def _choose_outdir(self):
        d = filedialog.askdirectory(title="Scegli cartella di output")
        if d:
            self._output_dir = Path(d)
            self._outdir_lbl.configure(text=str(self._output_dir))

    def _reset_outdir(self):
        self._output_dir = None
        self._outdir_lbl.configure(text="Stessa cartella dei file originali")

    # ── Conversione ────────────────────────────────────────────────────────────
    def _start_conversion(self):
        if self._converting:
            return
        if not self._file_rows:
            messagebox.showwarning("Nessun file",
                                   "Aggiungi almeno un'immagine prima di convertire.")
            return

        self._converting = True
        self._convert_btn.configure(state="disabled", text="⏳  Conversione in corso…")
        self._progress.set(0)

        threading.Thread(target=self._run_conversion, daemon=True).start()

    def _run_conversion(self):
        fmt       = self._fmt_var.get()
        quality   = int(self._quality_slider.get())
        strip_meta = self._strip_var.get()
        ext       = EXT_MAP[fmt]

        try:
            w_str = self._w_entry.get().strip()
            h_str = self._h_entry.get().strip()
            target_w = int(w_str) if w_str else None
            target_h = int(h_str) if h_str else None
        except ValueError:
            self.after(0, lambda: messagebox.showerror(
                "Errore", "Larghezza e altezza devono essere numeri interi."))
            self._finish_conversion(0, 0)
            return

        total = len(self._file_rows)
        ok = 0

        for i, row in enumerate(self._file_rows):
            row.set_status("⏳", "#aaaaaa")
            try:
                img = Image.open(row.file_path)

                # Preserva profilo colore ICC
                icc = img.info.get("icc_profile")

                # Gestione trasparenza per formati che non la supportano
                if fmt in ("JPEG", "BMP") and img.mode in ("RGBA", "P", "LA"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    mask = img.split()[-1] if img.mode in ("RGBA", "LA") else None
                    bg.paste(img, mask=mask)
                    img = bg
                elif fmt not in ("GIF",) and img.mode == "P":
                    img = img.convert("RGBA")
                elif img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                    img = img.convert("RGB")

                # Ridimensionamento proporzionale (mai ingrandisce)
                if target_w or target_h:
                    tw = target_w or img.width
                    th = target_h or img.height
                    ratio = min(tw / img.width, th / img.height, 1.0)
                    nw = max(1, int(img.width  * ratio))
                    nh = max(1, int(img.height * ratio))
                    img = img.resize((nw, nh), Image.LANCZOS)

                # Percorso output
                out_dir = self._output_dir or row.file_path.parent
                out_path = out_dir / (row.file_path.stem + "_converted" + ext)
                # Evita sovrascritture
                counter = 1
                while out_path.exists():
                    out_path = out_dir / (
                        f"{row.file_path.stem}_converted_{counter}{ext}")
                    counter += 1

                # Parametri di salvataggio per formato
                kw: dict = {}
                if fmt == "JPEG":
                    kw = {"quality": quality, "optimize": True, "progressive": True}
                    if icc and not strip_meta:
                        kw["icc_profile"] = icc
                elif fmt == "PNG":
                    compress = max(0, min(9, round((100 - quality) / 11)))
                    kw = {"compress_level": compress, "optimize": True}
                elif fmt == "WebP":
                    kw = {"quality": quality, "method": 4}
                elif fmt == "TIFF":
                    kw = {"compression": "tiff_lzw"}
                elif fmt == "GIF":
                    kw = {"optimize": True}

                img.save(out_path, format=fmt, **kw)

                # Calcolo risparmio
                orig  = row.file_path.stat().st_size
                saved = out_path.stat().st_size
                delta = round((1 - saved / orig) * 100) if orig else 0

                if delta > 0:
                    row.set_status(f"✓ -{delta}%", "#4caf50")
                elif delta < 0:
                    row.set_status(f"✓ +{-delta}%", "#ff9800")
                else:
                    row.set_status("✓", "#4caf50")

                ok += 1

            except Exception as exc:
                row.set_status("✗ errore", "#f44336")
                print(f"[ERRORE] {row.file_path.name}: {exc}")

            self.after(0, self._progress.set, (i + 1) / total)

        self._finish_conversion(ok, total)

    def _finish_conversion(self, ok: int, total: int):
        def _ui():
            self._convert_btn.configure(state="normal", text="▶  Converti tutto")
            self._converting = False
            self._status_lbl.configure(
                text=f"✓ {ok}/{total} convertit{'e' if ok != 1 else 'a'} con successo"
                if ok else "Nessun file convertito."
            )
            if ok == total and total > 0:
                self._progress.configure(progress_color="#4caf50")
            elif ok < total and ok > 0:
                self._progress.configure(progress_color="#ff9800")
            else:
                self._progress.configure(progress_color="#f44336")
        self.after(0, _ui)


# ── Avvio ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
