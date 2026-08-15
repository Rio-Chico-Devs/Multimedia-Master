"""
mBART-50 engine — optional, heavier alternative to argostranslate.

facebook/mbart-large-50-many-to-many-mmt (Hugging Face, MIT-licensed via
fairseq, the codebase it was trained with) is one general-purpose model
covering 50 languages, instead of argostranslate's small per-language-pair
models. It is downloaded once (~2.3 GB) and cached locally by `transformers`;
every call after that loads only from the local cache.

Offline guarantee: the first call per language pair tries
`local_files_only=True` and only falls back to a network fetch if the files
aren't cached yet. Once cached, this engine never touches the network again —
even if Hugging Face's servers are unreachable — which is the whole point of
offering it alongside argostranslate rather than a cloud API.

Trade-off vs argostranslate: much heavier dependency (transformers + torch),
slower per paragraph (one big multilingual model vs. a tiny pair-specific
one), so this is opt-in, not the default engine.

Language codes: mBART-50 needs its own locale tags (e.g. "it_IT", not "it").
Rather than hand-type the 50-entry table from memory — a wrong tag would
silently produce garbage translations, the exact failure mode this engine
exists to avoid — the mapping is read at runtime from the tokenizer's own
`lang_code_to_id`, keyed by the ISO 639-1 prefix this app already uses
elsewhere ("it" -> "it_IT").
"""
from __future__ import annotations

from common.depmsg import pip_hint
from .translate_engine import split_for_model

_MAX_INPUT_TOKENS = 512

_MODEL_NAME = "facebook/mbart-large-50-many-to-many-mmt"

_tokenizer = None
_model = None

# Display names for the Translate tab's language pickers. mBART-50 supports
# more languages than this; codes without a friendly name here still work,
# they just show their raw ISO 639-1 code instead of an Italian label.
_DISPLAY_NAMES = {
    "en": "Inglese", "it": "Italiano", "fr": "Francese", "de": "Tedesco",
    "es": "Spagnolo", "pt": "Portoghese", "nl": "Olandese", "pl": "Polacco",
    "ru": "Russo", "zh": "Cinese", "ja": "Giapponese", "ko": "Coreano",
    "ar": "Arabo", "tr": "Turco", "cs": "Ceco", "ro": "Romeno",
    "sv": "Svedese", "fi": "Finlandese", "uk": "Ucraino", "hi": "Hindi",
    "vi": "Vietnamita", "th": "Thailandese", "id": "Indonesiano",
}


class MbartUnavailable(Exception):
    pass


def _require_mbart() -> None:
    try:
        import transformers  # noqa: F401
    except ImportError as exc:
        raise MbartUnavailable(
            pip_hint("transformers torch sentencepiece")) from exc


def _load_tokenizer():
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer
    _require_mbart()
    from transformers import MBart50TokenizerFast

    try:
        _tokenizer = MBart50TokenizerFast.from_pretrained(
            _MODEL_NAME, local_files_only=True)
    except OSError:
        # Not cached yet: one-time download, exactly like an argostranslate
        # language package. Everything after this stays fully offline.
        _tokenizer = MBart50TokenizerFast.from_pretrained(_MODEL_NAME)
    return _tokenizer


def _load_model():
    global _model
    if _model is not None:
        return _model
    _load_tokenizer()
    from transformers import MBartForConditionalGeneration

    try:
        _model = MBartForConditionalGeneration.from_pretrained(
            _MODEL_NAME, local_files_only=True)
    except OSError:
        _model = MBartForConditionalGeneration.from_pretrained(_MODEL_NAME)
    _model.eval()
    return _model


def available() -> bool:
    try:
        _require_mbart()
        return True
    except MbartUnavailable:
        return False


def language_codes() -> dict[str, str]:
    """ISO 639-1 code -> mBART-50 locale code, e.g. {"it": "it_IT"}."""
    tok = _load_tokenizer()
    return {code.split("_")[0]: code for code in tok.lang_code_to_id}


def display_name(iso_code: str) -> str:
    return _DISPLAY_NAMES.get(iso_code, iso_code)


def translate(text: str, src: str, tgt: str) -> str:
    if not text.strip():
        return text
    tok = _load_tokenizer()
    langs = {code.split("_")[0]: code for code in tok.lang_code_to_id}
    if src not in langs or tgt not in langs:
        raise MbartUnavailable(f"mBART-50 non supporta la coppia {src}->{tgt}.")

    model = _load_model()
    import torch

    tok.src_lang = langs[src]
    tgt_id = tok.lang_code_to_id[langs[tgt]]

    # Chunk before encoding. Feeding a whole paragraph in one shot let the
    # tokenizer truncate at the limit and drop the tail, so a long paragraph
    # came back half translated with the call still reporting success.
    def _count(s: str) -> int:
        return len(tok(s)["input_ids"])

    out_parts: list[str] = []
    for chunk in split_for_model(text, _MAX_INPUT_TOKENS, _count):
        encoded = tok(chunk, return_tensors="pt",
                      truncation=True, max_length=_MAX_INPUT_TOKENS)
        with torch.no_grad():
            generated = model.generate(
                **encoded,
                forced_bos_token_id=tgt_id,
                max_new_tokens=_MAX_INPUT_TOKENS,
            )
        out_parts.append(tok.batch_decode(generated, skip_special_tokens=True)[0])
    return " ".join(p.strip() for p in out_parts if p.strip())
