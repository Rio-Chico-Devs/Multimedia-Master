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
  collapsing whitespace, splitting glued English words back apart with the
  optional `wordninja` package (MIT-licensed, offline, ships its own
  word-frequency dictionary), then running a conservative spell/OCR pass
  (`pyspellchecker`, offline dictionaries for en/it/fr/de/es/pt/nl/ru/ar) that
  fixes single-character misreads like "1n" -> "in" while leaving acronyms,
  part numbers and unknown technical terms untouched. All of this is
  best-effort: if a package isn't installed that step is skipped, never crashing.

Glossary technique (term protection):
  Each glossary term is replaced by a unique placeholder token *before*
  translation, then the token is swapped for the desired translation
  *after*. This survives the MT model's reordering far better than trying
  to post-process its raw output, though small models occasionally still
  mangle a token — acceptable for a deterministic, fully offline pipeline.

Language packages must be downloaded once (requires internet — see
list_downloadable_pairs()/install_pair()); translation itself never touches
the network afterwards.

Alternative engine: translate_text(..., engine="mbart") routes through
mbart_engine.py (facebook/mbart-large-50-many-to-many-mmt) instead — one
larger general-purpose multilingual model rather than many small per-pair
ones. Same offline guarantee, heavier dependency, slower per paragraph.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache

from common.depmsg import pip_hint


def _configure_argos_threads() -> None:
    """Let CTranslate2 (argostranslate's inference backend) use the machine's
    cores for each translation. argostranslate reads ARGOS_INTER_THREADS
    (parallel translators, default "1") and ARGOS_INTRA_THREADS (threads per
    translation, default "0" = a conservative auto value) from the environment
    at import time, and env vars take priority over its settings file.

    We translate one paragraph at a time, so the lever that helps is
    intra_threads — more cores working on each paragraph lowers its latency.
    CTranslate2's guidance is to keep inter_threads * intra_threads at or below
    the physical core count, so with inter_threads left at 1 we set
    intra_threads to the core count (capped — past ~8 the gain flattens and the
    thread overhead grows). setdefault() means an explicit user override always
    wins.

    Sources:
      - argostranslate settings: ARGOS_INTER_THREADS / ARGOS_INTRA_THREADS
        (github.com/argosopentech/argos-translate settings.py)
      - CTranslate2 multithreading guidance (opennmt.net/CTranslate2/parallel)
    """
    cores = os.cpu_count() or 1
    os.environ.setdefault("ARGOS_INTRA_THREADS", str(max(1, min(cores, 8))))


_configure_argos_threads()


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


@lru_cache(maxsize=50000)
def _split_glued_word(token: str) -> str:
    """Best-effort split of an OCR-glued English token ('POWERUNITS' ->
    'POWER UNITS').

    Cached: a manual reuses the same vocabulary thousands of times, and each
    miss runs wordninja's splitter plus a per-piece re-split verification —
    pure-Python work that holds the GIL and so competes with the UI thread.
    Memoising collapses all repeats of a token to a single dict lookup.

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


# ── Conservative OCR spell correction ────────────────────────────────────────
# pyspellchecker ships its own frequency dictionaries for these languages and
# runs fully offline. For any other source language we skip correction entirely
# rather than guess with the wrong dictionary. (Package name: pyspellchecker;
# import name: spellchecker.)
_PYSPELL_LANGS = frozenset(
    {"en", "es", "fr", "pt", "de", "it", "ru", "ar", "nl", "lv", "eu"})
_spellers: dict[str, object] = {}
_spell_tried: set[str] = set()
# A word token: letters/digits, allowing an internal apostrophe (don't, l'OCR is
# split by the source already). Digits are admitted so OCR misreads like "1n"
# (for "in") are seen as one token and can be corrected, not skipped as noise.
_TOKEN_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z'’]*")
_SENTENCE_END = frozenset({".", "!", "?", ":", ";"})


def _get_speller(lang: str):
    """Lazily build (and cache) a pyspellchecker for `lang`. Returns None if the
    language is unsupported or the optional package isn't installed, so spell
    correction degrades to a no-op rather than an error."""
    if lang not in _PYSPELL_LANGS:
        return None
    if lang not in _spell_tried:
        _spell_tried.add(lang)
        try:
            from spellchecker import SpellChecker
            sp = SpellChecker(language=lang)
            # Edit distance 1: OCR misreads are single-character substitutions
            # ("1n" -> "in"). Allowing distance 2 multiplies the candidate set
            # and starts "correcting" perfectly good rare words into common
            # ones, which is exactly the damage we must avoid on a manual.
            sp.distance = 1
            _spellers[lang] = sp
        except Exception:
            _spellers[lang] = None
    return _spellers.get(lang)


def _is_protected_token(tok: str) -> bool:
    """True for tokens we must never "correct": acronyms, part numbers and other
    codes. Wrongly normalising "BCS", "12V" or "kVA" in a technical manual is
    worse than leaving a real typo, so the rule is deliberately cautious — only
    plain words (and a single-digit OCR slip like "1n") get past it."""
    digits = sum(c.isdigit() for c in tok)
    if digits:
        # A lone digit among lowercase letters is a plausible OCR misread
        # ("1n", "5un"); anything else with digits is treated as a code.
        if digits == 1 and not any(c.isupper() for c in tok):
            return False
        return True
    if tok.isupper() and len(tok) >= 2:        # BCS, ABS, USA
        return True
    if any(c.isupper() for c in tok[1:]):      # kVA, McLaren, PnP
        return True
    return False


@lru_cache(maxsize=50000)
def _correct_token(tok: str, lang: str) -> str:
    """Best-effort single-token correction. Returns the token unchanged unless
    the speller is confident: the lowercased token is genuinely unknown and has
    exactly one in-dictionary correction within edit distance 1. Cached because
    a manual repeats its vocabulary thousands of times and each miss runs
    pyspellchecker's candidate search (pure-Python, holds the GIL)."""
    sp = _get_speller(lang)
    if sp is None or len(tok) < 2 or _is_protected_token(tok):
        return tok
    low = tok.lower()
    # Known word: leave it (and its original casing) completely alone.
    if not sp.unknown([low]):
        return tok
    corr = sp.correction(low)
    if not corr or corr == low:
        return tok
    return corr


def _restore_case(original: str, corrected: str, at_sentence_start: bool) -> str:
    """Re-apply the original token's capitalisation to a lowercase correction so
    a fix never silently changes the casing of surrounding prose. A correction
    of a sentence-initial OCR slip ("1n" -> "In") is capitalised even though the
    digit it replaced carried no case."""
    if corrected == original:
        return corrected
    if original[:1].isupper() or at_sentence_start:
        return corrected[:1].upper() + corrected[1:]
    return corrected


def _spell_correct(text: str, lang: str) -> str:
    """Run conservative spell/OCR correction over `text`. Walks token by token,
    tracking sentence starts for capitalisation, and rebuilds the string with
    every non-word character (spaces, punctuation) preserved exactly."""
    if _get_speller(lang) is None:
        return text
    out: list[str] = []
    pos = 0
    at_sentence_start = True
    for m in _TOKEN_RE.finditer(text):
        gap = text[pos:m.start()]
        if gap:
            out.append(gap)
            stripped = gap.rstrip()
            if stripped and stripped[-1] in _SENTENCE_END:
                at_sentence_start = True
            elif gap.strip():
                at_sentence_start = False
        tok = m.group(0)
        corrected = _correct_token(tok, lang)
        out.append(_restore_case(tok, corrected, at_sentence_start))
        at_sentence_start = False
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def _preprocess_source(text: str, src: str) -> str:
    """Clean OCR/PDF artefacts out of the source text before it reaches the
    MT model: whitespace is always normalised; glued English words are split
    back apart (wordninja, English-only); then a conservative spell/OCR pass
    fixes single-character misreads for any language pyspellchecker covers,
    leaving acronyms, codes and unknown technical terms untouched."""
    text = re.sub(r"\s+", " ", text).strip()
    if src == "en":
        text = _WORD_RE.sub(lambda m: _split_glued_word(m.group(0)), text)
    text = _spell_correct(text, src)
    return text


def clean_extracted_text(text: str, src: str) -> str:
    """Public entry point for the same OCR/PDF artefact cleanup translate_text()
    applies automatically. extract_sections() calls this so the pre-translation
    review screen already shows de-glued text — not just the final translation —
    since that screen is the user's only chance to fix garbled OCR before it
    gets baked into the document. Re-running it later inside translate_text() on
    already-cleaned text is harmless: whitespace squeezing is idempotent, and a
    token that already split correctly is left whole (it has no more glue to
    find)."""
    return _preprocess_source(text, src)


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
                    glossary: dict[str, str] | None = None,
                    engine: str = "argos") -> str:
    """Translate one chunk of text (line/paragraph), honouring an optional
    glossary. `engine` is "argos" (default, small per-pair models) or
    "mbart" (facebook/mbart-large-50-many-to-many-mmt, see mbart_engine.py)."""
    if not text.strip():
        return text

    text = _preprocess_source(text, src)

    def _mt(chunk: str) -> str:
        if engine == "mbart":
            from . import mbart_engine
            return mbart_engine.translate(chunk, src, tgt)
        _require_argos()
        import argostranslate.translate as at
        return at.translate(chunk, src, tgt)

    if glossary:
        protected, tokens = _protect_glossary(text, glossary)
        translated = _mt(protected)
        for token, repl in tokens.items():
            translated = translated.replace(token, repl)
        return translated

    return _mt(text)
