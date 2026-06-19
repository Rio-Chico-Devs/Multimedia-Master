"""
Translate Engine — offline, sentence-level machine translation via argostranslate.

Fully offline once language packages are installed: argostranslate ships small
per-language-pair neural models (CTranslate2, runs on CPU) that, unlike naive
word-for-word substitution, translate whole sentences with normal grammar and
word order. It is not a large general-purpose LLM, so domain nuance is more
limited — the glossary mechanism below is the offline-friendly way to pin down
sector-specific terminology the model would otherwise translate inconsistently.

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

    if glossary:
        protected, tokens = _protect_glossary(text, glossary)
        translated = at.translate(protected, src, tgt)
        for token, repl in tokens.items():
            translated = translated.replace(token, repl)
        return translated

    return at.translate(text, src, tgt)
