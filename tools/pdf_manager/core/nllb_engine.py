"""
NLLB-200 engine — optional, higher-quality alternative to argostranslate.

facebook/nllb-200-distilled-600M (Hugging Face, CC-BY-NC-4.0 weights, code
MIT) is Meta's "No Language Left Behind" multilingual model. The distilled
600M variant is roughly the same weight class as mBART-50 but generally
translates more naturally and less literally on the European pairs this app
targets, which is exactly the complaint it exists to answer here.

Offline guarantee: like mbart_engine, the first load per process tries
`local_files_only=True` and only falls back to a one-time network fetch if the
weights aren't cached yet (~2.4 GB). Once cached it never touches the network
again — the whole point of bundling it instead of calling a cloud API.

Two deliberate differences from mbart_engine, both lessons from it:
  * language_codes() is a *static* table, so merely selecting NLLB in the UI
    populates the language pickers without loading the model — the multi-GB
    download is deferred until the user actually translates something.
  * translate() splits a paragraph into sentences and translates each one,
    rejoining the results. NLLB (like mBART) silently truncates input past its
    token limit; a manual's paragraphs can be long, so sentence-by-sentence
    keeps every sentence well under the limit and never drops text.

Language codes: NLLB uses FLORES-200 tags ("eng_Latn", "ita_Latn"), not the
ISO 639-1 codes ("en", "it") this app uses elsewhere. The mapping below is the
curated subset we expose; translate() resolves the target tag to a token id via
the tokenizer's own vocabulary (convert_tokens_to_ids), which is the API that
survived transformers dropping the old lang_code_to_id dict.
"""
from __future__ import annotations

from common.depmsg import pip_hint

_MODEL_NAME = "facebook/nllb-200-distilled-600M"

_tokenizer = None
_model = None

# ISO 639-1 -> FLORES-200 code. Curated to the languages worth offering for a
# European technical-manual workflow plus the common CJK/RTL ones; extend as
# needed (every value must be a real FLORES-200 tag or translate() will reject
# the pair rather than silently produce garbage).
_FLORES = {
    "en": "eng_Latn", "it": "ita_Latn", "fr": "fra_Latn", "de": "deu_Latn",
    "es": "spa_Latn", "pt": "por_Latn", "nl": "nld_Latn", "pl": "pol_Latn",
    "ru": "rus_Cyrl", "uk": "ukr_Cyrl", "cs": "ces_Latn", "ro": "ron_Latn",
    "sv": "swe_Latn", "fi": "fin_Latn", "da": "dan_Latn", "nb": "nob_Latn",
    "hu": "hun_Latn", "ca": "cat_Latn", "tr": "tur_Latn", "el": "ell_Grek",
    "ar": "arb_Arab", "zh": "zho_Hans", "ja": "jpn_Jpan", "ko": "kor_Hang",
    "hi": "hin_Deva", "vi": "vie_Latn", "id": "ind_Latn", "th": "tha_Thai",
}

_DISPLAY_NAMES = {
    "en": "Inglese", "it": "Italiano", "fr": "Francese", "de": "Tedesco",
    "es": "Spagnolo", "pt": "Portoghese", "nl": "Olandese", "pl": "Polacco",
    "ru": "Russo", "uk": "Ucraino", "cs": "Ceco", "ro": "Romeno",
    "sv": "Svedese", "fi": "Finlandese", "da": "Danese", "nb": "Norvegese",
    "hu": "Ungherese", "ca": "Catalano", "tr": "Turco", "el": "Greco",
    "ar": "Arabo", "zh": "Cinese", "ja": "Giapponese", "ko": "Coreano",
    "hi": "Hindi", "vi": "Vietnamita", "id": "Indonesiano", "th": "Thailandese",
}

# A paragraph is split here before translation so no single chunk overruns the
# model's token limit (which would silently truncate text). Splits after .!?…
# when followed by whitespace; abbreviations occasionally cause an early split,
# harmless since each fragment is still translated and rejoined in order.
import re  # noqa: E402  (kept next to the pattern it defines, for locality)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_MAX_INPUT_TOKENS = 512


class NllbUnavailable(Exception):
    pass


def _require_nllb() -> None:
    try:
        import transformers  # noqa: F401
    except ImportError as exc:
        raise NllbUnavailable(
            pip_hint("transformers torch sentencepiece")) from exc


def _load_tokenizer():
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer
    _require_nllb()
    from transformers import AutoTokenizer

    try:
        _tokenizer = AutoTokenizer.from_pretrained(
            _MODEL_NAME, local_files_only=True)
    except OSError:
        # Not cached yet: one-time download, then fully offline forever after.
        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
    return _tokenizer


def _load_model():
    global _model
    if _model is not None:
        return _model
    _load_tokenizer()
    from transformers import AutoModelForSeq2SeqLM

    try:
        _model = AutoModelForSeq2SeqLM.from_pretrained(
            _MODEL_NAME, local_files_only=True)
    except OSError:
        _model = AutoModelForSeq2SeqLM.from_pretrained(_MODEL_NAME)
    _model.eval()
    return _model


def available() -> bool:
    """True if the heavy dependencies are importable. Does NOT load the model
    (no download), so the UI can offer the engine and list languages first and
    only pay the multi-GB cost when the user actually translates."""
    try:
        _require_nllb()
        return True
    except NllbUnavailable:
        return False


def language_codes() -> dict[str, str]:
    """ISO 639-1 code -> NLLB/FLORES-200 code, e.g. {"it": "ita_Latn"}.

    Static on purpose: returning this without loading the tokenizer is what lets
    the UI populate its language pickers the instant NLLB is selected, deferring
    the model download to the first real translation."""
    return dict(_FLORES)


def display_name(iso_code: str) -> str:
    return _DISPLAY_NAMES.get(iso_code, iso_code)


def _split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_SPLIT.split(text)]
    return [s for s in parts if s]


def translate(text: str, src: str, tgt: str) -> str:
    if src not in _FLORES or tgt not in _FLORES:
        raise NllbUnavailable(f"NLLB-200 non supporta la coppia {src}->{tgt}.")
    if not text.strip():
        return text

    tok = _load_tokenizer()
    model = _load_model()
    import torch

    tgt_id = tok.convert_tokens_to_ids(_FLORES[tgt])
    tok.src_lang = _FLORES[src]

    # Translate sentence by sentence so a long paragraph never overruns the
    # token limit (which truncates text); rejoin in order with a single space.
    out_parts: list[str] = []
    for sentence in _split_sentences(text) or [text]:
        encoded = tok(sentence, return_tensors="pt",
                      truncation=True, max_length=_MAX_INPUT_TOKENS)
        with torch.no_grad():
            generated = model.generate(
                **encoded,
                forced_bos_token_id=tgt_id,
                max_new_tokens=_MAX_INPUT_TOKENS,
            )
        out_parts.append(tok.batch_decode(generated, skip_special_tokens=True)[0])
    return " ".join(p.strip() for p in out_parts if p.strip())
