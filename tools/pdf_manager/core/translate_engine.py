"""
Translate Engine — offline, sentence-level machine translation via argostranslate.

Fully offline once language packages are installed: argostranslate ships small
per-language-pair neural models (CTranslate2, runs on CPU) that, unlike naive
word-for-word substitution, translate whole sentences with normal grammar and
word order. It is not a large general-purpose LLM, so domain nuance is more
limited — the glossary mechanism below is the offline-friendly way to pin down
sector-specific terminology the model would otherwise translate inconsistently.

Source cleanup (why it matters so much here):
  A small NMT model is only as good as the text it's fed. Scanned/OCR'd pages
  routinely glue words together ("POWER UNITS" -> "POWERUNITS") and PDFs break
  words across lines with hyphens ("attach-ments"). Feeding those straight to
  the model produces exactly the garbage the user sees ("POTENZAUNITI", half a
  sentence left untranslated). _preprocess_source() cleans the text first —
  collapsing whitespace and, for English source, splitting glued words back
  apart with the optional `wordninja` package (MIT-licensed, offline, ships its
  own word-frequency dictionary). All of this is best-effort: if wordninja
  isn't installed the text is passed through unchanged, never crashing.

Glossary technique (term protection):
  Each glossary term is replaced by a unique placeholder token *before*
  translation, then the token is swapped for the desired translation
  *after*. This survives the MT model's reordering far better than trying
  to post-process its raw output, though small models occasionally still
  mangle a token — acceptable for a deterministic, fully offline pipeline.

Language packages must be downloaded once (requires internet — see
list_downloadable_pairs()/install_pair()); translation itself never touches
the network afterwards.
"""
from __future__ import annotations

import re

from common.depmsg import pip_hint


class TranslateUnavailable(Exception):
    pass


def _require_argos():
    try:
        import argostranslate.translate  # noqa: F401
    except ImportError as exc:
        raise TranslateUnavailable(pip_hint("argostranslate")) from exc


def installed_pairs() -> list[tuple[str, str, str, str]]:
    """List of (from_code, from_name, to_code, to_name) for installed packages."""
    _require_argos()
    import argostranslate.translate as at

    # `translations_from` holds the translations where `lang` is the SOURCE
    # (argostranslate's Language.get_translation filters this same list). Read
    # the source/target off each translation object directly and skip identity
    # (en->en) entries, which argostranslate auto-adds for every installed
    # language and are useless / confusing in the language pickers.
    pairs = []
    for lang in at.get_installed_languages():
        for tr in lang.translations_from:
            f, t = tr.from_lang, tr.to_lang
            if f.code == t.code:
                continue
            pairs.append((f.code, f.name, t.code, t.name))
    return pairs


def is_pair_installed(src: str, tgt: str) -> bool:
    return any(f == src and t == tgt for f, _, t, _ in installed_pairs())


def list_downloadable_pairs() -> list[tuple[str, str, str, str]]:
    """Query the online package index. Requires internet — call from a worker thread."""
    _require_argos()
    import argostranslate.package as ap

    ap.update_package_index()
    return [(p.from_code, p.from_name, p.to_code, p.to_name)
            for p in ap.get_available_packages()]


def install_pair(src: str, tgt: str) -> None:
    """Download and install one language-pair package. Requires internet."""
    _require_argos()
    import argostranslate.package as ap

    ap.update_package_index()
    pkg = next((p for p in ap.get_available_packages()
                if p.from_code == src and p.to_code == tgt), None)
    if pkg is None:
        raise TranslateUnavailable(f"Pacchetto {src}→{tgt} non disponibile.")
    ap.install_from_path(pkg.download())


_wordninja = None
_wordninja_tried = False
# 6+ letters: long enough that a glued run is plausible, short enough to still
# catch things like "Afront" ("A front"). Real words this length survive
# untouched because wordninja keeps a known word whole (see _split_glued_word).
_WORD_RE = re.compile(r"[A-Za-z]{6,}")
# "a" and "i" are the only real one-letter English words; allow them as split
# pieces but treat any other lone letter as a sign we over-split.
_OK_SINGLE_LETTERS = frozenset({"a", "i"})


def _get_wordninja():
    """Lazily import the optional `wordninja` splitter. Returns None if it
    isn't installed — de-gluing then becomes a no-op, never an error."""
    global _wordninja, _wordninja_tried
    if not _wordninja_tried:
        _wordninja_tried = True
        try:
            import wordninja
            _wordninja = wordninja
        except Exception:
            _wordninja = None
    return _wordninja


def _split_glued_word(token: str) -> str:
    """Best-effort split of an OCR-glued English token ('POWERUNITS' ->
    'POWER UNITS').

    Conservative on purpose: a genuine single word (even a long one) splits
    to itself, so we only break a token when wordninja finds >= 2 pieces that
    are each themselves whole words. Anything we're unsure about is returned
    untouched, so real technical terms and part numbers survive intact.

    Lone letters other than "a"/"i" are rejected — those signal that we
    shattered a word we shouldn't have (e.g. a part code), whereas the common
    real glue cases ("Apusherhasthe..." -> "A pusher has the...",
    "201isatractor" -> "is a tractor") legitimately contain "a" and "i".
    """
    wn = _get_wordninja()
    if wn is None:
        return token
    try:
        parts = wn.split(token)
    except Exception:
        return token
    if len(parts) < 2:
        return token
    for p in parts:
        if len(p) == 1 and p.lower() not in _OK_SINGLE_LETTERS:
            return token
    # Each piece must be "atomic" to wordninja (re-splitting leaves it whole),
    # otherwise we'd be shattering an unknown word into letter soup.
    for p in parts:
        try:
            if wn.split(p) != [p]:
                return token
        except Exception:
            return token
    return " ".join(parts)


def _preprocess_source(text: str, src: str) -> str:
    """Clean OCR/PDF artefacts out of the source text before it reaches the
    MT model. Whitespace is always normalised; glued-word splitting only runs
    for English source (wordninja is English-only)."""
    text = re.sub(r"\s+", " ", text).strip()
    if src == "en":
        text = _WORD_RE.sub(lambda m: _split_glued_word(m.group(0)), text)
    return text


def _protect_glossary(text: str, glossary: dict[str, str]) -> tuple[str, dict[str, str]]:
    tokens: dict[str, str] = {}
    protected = text
    for i, (term, repl) in enumerate(glossary.items()):
        if not term:
            continue
        token = f"XPH{i}X"
        protected, n = re.subn(rf"\b{re.escape(term)}\b", token, protected,
                                flags=re.IGNORECASE)
        if n:
            tokens[token] = repl
    return protected, tokens


def translate_text(text: str, src: str, tgt: str,
                    glossary: dict[str, str] | None = None) -> str:
    """Translate one chunk of text (line/paragraph), honouring an optional glossary."""
    _require_argos()
    import argostranslate.translate as at

    if not text.strip():
        return text

    text = _preprocess_source(text, src)

    if glossary:
        protected, tokens = _protect_glossary(text, glossary)
        translated = at.translate(protected, src, tgt)
        for token, repl in tokens.items():
            translated = translated.replace(token, repl)
        return translated

    return at.translate(text, src, tgt)
