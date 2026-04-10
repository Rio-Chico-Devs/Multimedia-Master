"""
PDF Engine — pure business logic, zero UI dependencies.

Every public method returns a result dataclass.
Optional libraries (pytesseract, pdfplumber) are imported lazily;
the engine degrades gracefully when they are not available.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Result dataclasses ─────────────────────────────────────────────────────────

@dataclass
class PdfResult:
    output:     Path | None
    success:    bool
    page_count: int  = 0
    file_size:  int  = 0
    error:      str  = ""


@dataclass
class PdfAnalysis:
    page_count:       int
    word_count:       int
    char_count:       int
    full_text:        str
    summary:          str
    encrypted:        bool
    has_acroform:     bool
    form_fields:      list[str]         # AcroForm field names
    suggested_fields: list[str]         # visually detected (OCR/pattern)
    metadata:         dict[str, str]


# ── Engine ─────────────────────────────────────────────────────────────────────

class PdfEngine:
    """
    All PDF operations in one place.

    Dependencies:
      required : pypdf, reportlab, Pillow
      optional : pdfplumber (richer text extraction), pytesseract (OCR)
    """

    # ── Images → PDF ──────────────────────────────────────────────────────────

    def images_to_pdf(
        self,
        images:       list[Path],
        output:       Path,
        ocr:          bool = False,
        one_per_file: bool = False,
        lang:         str  = "ita+eng",
    ) -> list[PdfResult]:
        """Convert image files to PDF(s). Returns one result per output file."""
        if one_per_file:
            results = []
            for img in images:
                out = output.parent / (img.stem + ".pdf")
                out = self._unique_path(out)
                results.append(self._img_to_pdf(img, out, ocr, lang))
            return results
        else:
            return [self._imgs_to_single_pdf(images, output, ocr, lang)]

    def _img_to_pdf(self, img: Path, output: Path,
                    ocr: bool, lang: str) -> PdfResult:
        return self._ocr_to_pdf([img], output, lang) if ocr \
               else self._reportlab_to_pdf([img], output)

    def _imgs_to_single_pdf(self, images: list[Path], output: Path,
                             ocr: bool, lang: str) -> PdfResult:
        return self._ocr_to_pdf(images, output, lang) if ocr \
               else self._reportlab_to_pdf(images, output)

    def _reportlab_to_pdf(self, images: list[Path], output: Path) -> PdfResult:
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.utils import ImageReader
            from PIL import Image

            c = canvas.Canvas(str(output))
            for img_path in images:
                with Image.open(img_path) as img:
                    img_rgb = img.convert("RGB")
                    w, h = img_rgb.size
                    c.setPageSize((w, h))
                    buf = io.BytesIO()
                    img_rgb.save(buf, format="JPEG", quality=92)
                    buf.seek(0)
                    c.drawImage(ImageReader(buf), 0, 0, w, h)
                c.showPage()
            c.save()
            return self._ok(output)
        except Exception as exc:
            return PdfResult(output=output, success=False, error=str(exc))

    def _ocr_to_pdf(self, images: list[Path], output: Path,
                    lang: str) -> PdfResult:
        try:
            import pytesseract
            from PIL import Image
            from pypdf import PdfWriter, PdfReader

            writer = PdfWriter()
            for img_path in images:
                with Image.open(img_path) as img:
                    pdf_bytes = pytesseract.image_to_pdf_or_hocr(
                        img, extension="pdf", lang=lang)
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    writer.add_page(page)

            with open(output, "wb") as f:
                writer.write(f)
            return self._ok(output)
        except ImportError:
            return PdfResult(
                output=output, success=False,
                error="OCR non disponibile: installa pytesseract e Tesseract OCR.")
        except Exception as exc:
            return PdfResult(output=output, success=False, error=str(exc))

    # ── Merge ─────────────────────────────────────────────────────────────────

    def merge(self, pdfs: list[Path], output: Path) -> PdfResult:
        """Merge multiple PDFs into one, preserving order."""
        try:
            from pypdf import PdfWriter, PdfReader

            writer = PdfWriter()
            for pdf in pdfs:
                reader = PdfReader(str(pdf))
                for page in reader.pages:
                    writer.add_page(page)

            with open(output, "wb") as f:
                writer.write(f)
            return self._ok(output)
        except Exception as exc:
            return PdfResult(output=output, success=False, error=str(exc))

    # ── Split ─────────────────────────────────────────────────────────────────

    def split_by_ranges(
        self, pdf: Path, ranges_str: str, output_dir: Path
    ) -> list[PdfResult]:
        """
        Split a PDF by page ranges.
        ranges_str format: "1-3, 5, 7-10"  (1-indexed, inclusive)
        """
        try:
            from pypdf import PdfReader, PdfWriter

            reader  = PdfReader(str(pdf))
            total   = len(reader.pages)
            results = []

            for spec in ranges_str.split(","):
                spec = spec.strip()
                if not spec:
                    continue
                if "-" in spec:
                    s, e = spec.split("-", 1)
                    start, end = int(s) - 1, int(e) - 1
                else:
                    start = end = int(spec) - 1

                start = max(0, start)
                end   = min(total - 1, end)

                writer = PdfWriter()
                for i in range(start, end + 1):
                    writer.add_page(reader.pages[i])

                out = self._unique_path(
                    output_dir / f"{pdf.stem}_pag{start+1}-{end+1}.pdf")
                with open(out, "wb") as f:
                    writer.write(f)
                results.append(self._ok(out))

            return results
        except Exception as exc:
            return [PdfResult(output=None, success=False, error=str(exc))]

    def split_every_n(
        self, pdf: Path, n: int, output_dir: Path
    ) -> list[PdfResult]:
        """Split a PDF into chunks of N pages each."""
        try:
            from pypdf import PdfReader, PdfWriter

            reader  = PdfReader(str(pdf))
            total   = len(reader.pages)
            results = []

            for chunk, start in enumerate(range(0, total, n), start=1):
                end    = min(start + n, total)
                writer = PdfWriter()
                for i in range(start, end):
                    writer.add_page(reader.pages[i])

                out = self._unique_path(
                    output_dir / f"{pdf.stem}_parte{chunk}.pdf")
                with open(out, "wb") as f:
                    writer.write(f)
                results.append(self._ok(out))

            return results
        except Exception as exc:
            return [PdfResult(output=None, success=False, error=str(exc))]

    # ── Protect / Unlock ──────────────────────────────────────────────────────

    def protect(
        self,
        pdf:          Path,
        user_pw:      str,
        owner_pw:     str,
        output:       Path,
        allow_print:  bool = True,
        allow_copy:   bool = False,
    ) -> PdfResult:
        """Encrypt a PDF with AES-256."""
        try:
            from pypdf import PdfWriter, PdfReader

            reader = PdfReader(str(pdf))
            writer = PdfWriter()
            writer.clone_reader_document_root(reader)

            # Build permission flags (PDF spec bit positions)
            perms = 0
            if allow_print: perms |= (1 << 2) | (1 << 11)  # print + high quality
            if allow_copy:  perms |= (1 << 4)               # copy text

            writer.encrypt(
                user_password=user_pw,
                owner_password=owner_pw or user_pw,
                algorithm="AES-256-R5",
                permissions_flag=perms if perms else -4,
            )
            with open(output, "wb") as f:
                writer.write(f)
            return self._ok(output)
        except Exception as exc:
            return PdfResult(output=output, success=False, error=str(exc))

    def unlock(self, pdf: Path, password: str, output: Path) -> PdfResult:
        """Remove password protection from a PDF."""
        try:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(str(pdf))
            if reader.is_encrypted:
                result = reader.decrypt(password)
                if result.name == "NOT_DECRYPTED":
                    return PdfResult(output=output, success=False,
                                     error="Password errata o algoritmo non supportato.")

            writer = PdfWriter()
            writer.clone_reader_document_root(reader)
            with open(output, "wb") as f:
                writer.write(f)
            return self._ok(output)
        except Exception as exc:
            return PdfResult(output=output, success=False, error=str(exc))

    # ── Compress ──────────────────────────────────────────────────────────────

    def compress(self, pdf: Path, output: Path) -> PdfResult:
        """Reduce PDF file size by removing redundant objects."""
        try:
            from pypdf import PdfWriter

            writer = PdfWriter(clone_from=str(pdf))
            writer.compress_identical_objects(
                remove_identicals=True, remove_orphans=True)
            for page in writer.pages:
                page.compress_content_streams()

            with open(output, "wb") as f:
                writer.write(f)
            return self._ok(output)
        except Exception as exc:
            return PdfResult(output=output, success=False, error=str(exc))

    # ── Analyze ───────────────────────────────────────────────────────────────

    def analyze(self, pdf: Path, password: str = "") -> PdfAnalysis:
        """Extract text, metadata, form fields and generate a summary."""
        from pypdf import PdfReader

        reader = PdfReader(str(pdf))
        encrypted = reader.is_encrypted
        if encrypted and password:
            reader.decrypt(password)

        # Metadata
        meta: dict[str, str] = {}
        if reader.metadata:
            for k, v in reader.metadata.items():
                if v is not None:
                    meta[str(k).lstrip("/")] = str(v)

        # AcroForm fields
        fields     = reader.get_fields() or {}
        field_names = list(fields.keys())

        # Text extraction — prefer pdfplumber (better layout), fallback to pypdf
        full_text = self._extract_text(pdf, password, reader)

        # Visually detected form-like patterns
        suggested = self._detect_visual_fields(full_text)

        words = [w for w in full_text.split() if w.strip()]
        summary = self._extractive_summary(full_text)

        return PdfAnalysis(
            page_count=len(reader.pages),
            word_count=len(words),
            char_count=len(full_text),
            full_text=full_text,
            summary=summary,
            encrypted=encrypted,
            has_acroform=bool(field_names),
            form_fields=field_names,
            suggested_fields=suggested,
            metadata=meta,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_text(self, pdf: Path, password: str, fallback_reader) -> str:
        try:
            import pdfplumber
            kw = {"password": password} if password else {}
            with pdfplumber.open(str(pdf), **kw) as doc:
                pages = [p.extract_text() or "" for p in doc.pages]
            return "\n\n".join(pages)
        except Exception:
            # Fallback: pypdf text extraction
            pages = []
            for page in fallback_reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    pages.append("")
            return "\n\n".join(pages)

    @staticmethod
    def _detect_visual_fields(text: str) -> list[str]:
        """Heuristic detection of form-like labels in plain text."""
        patterns = [
            r'\b(nome|cognome|data\s+di\s+nascita|luogo\s+di\s+nascita|'
            r'codice\s+fiscale|indirizzo|cap|città|telefono|cellulare|'
            r'email|firma|data|importo|numero|matricola)\b',
            r'\b(name|surname|date\s+of\s+birth|address|phone|signature|'
            r'email|amount|number)\b',
        ]
        found = set()
        combined = "|".join(f"(?:{p})" for p in patterns)
        for m in re.finditer(combined, text, re.IGNORECASE):
            found.add(m.group(0).strip().title())
        return sorted(found)

    @staticmethod
    def _extractive_summary(text: str, n: int = 5) -> str:
        """Return the N most informative sentences (TF-based, offline)."""
        STOP = {
            "il","lo","la","i","gli","le","un","uno","una","di","a","da","in",
            "con","su","per","tra","fra","e","è","o","ma","se","che","non","si",
            "ha","hanno","del","della","dei","degli","delle","al","alla","ai",
            "the","a","an","and","or","but","in","on","at","to","for","of",
            "with","by","from","is","are","was","were","be","been","this","that",
        }
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) <= n:
            return text[:800]

        # Word frequency (skip stop words and short words)
        freq: dict[str, int] = {}
        for w in re.sub(r"[^\w\s]", " ", text).lower().split():
            if w not in STOP and len(w) > 2:
                freq[w] = freq.get(w, 0) + 1

        scored = []
        for i, sent in enumerate(sentences):
            if len(sent.split()) < 6:
                continue
            score = sum(freq.get(re.sub(r"[^\w]", "", w.lower()), 0)
                        for w in sent.split())
            # Sentences near the start carry a slight bonus
            bonus = 1.2 if i < len(sentences) * 0.25 else 1.0
            scored.append((score * bonus, i, sent))

        top = sorted(scored, reverse=True)[:n]
        top.sort(key=lambda x: x[1])          # restore original order
        return " ".join(s[2] for s in top) or text[:800]

    @staticmethod
    def _ok(output: Path) -> PdfResult:
        size = output.stat().st_size if output.exists() else 0
        return PdfResult(output=output, success=True,
                         file_size=size)

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        counter = 1
        while True:
            candidate = path.with_stem(f"{path.stem}_{counter}")
            if not candidate.exists():
                return candidate
            counter += 1
