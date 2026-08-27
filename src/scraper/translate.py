"""
Free translation via deep-translator (wraps Google Translate's free web
endpoint — no API key, no cost, no compiled dependencies to install).
Needs an internet connection, which the pipeline already requires anyway.

Translate only the short extracted fields (name, brand, ingredients text) —
never the whole page, it's wasted work and wasted requests.
"""

import re

_HTML_LANG_PATTERN = re.compile(r'<html[^>]+lang=["\']([a-zA-Z]{2})', re.I)


def detect_lang_from_html(html: str) -> str | None:
    match = _HTML_LANG_PATTERN.search(html)
    if match:
        return match.group(1).lower()
    return None


def detect_lang_from_text(text: str) -> str | None:
    try:
        from langdetect import detect
        return detect(text)
    except Exception:
        return None


def translate_to_en(text: str, from_code: str) -> str:
    if not text or from_code in ("en", None):
        return text
    try:
        from deep_translator import GoogleTranslator
        # deep-translator wants ISO codes; 'auto' is a safe fallback if the
        # detected code isn't one it recognises.
        try:
            return GoogleTranslator(source=from_code, target="en").translate(text)
        except Exception:
            return GoogleTranslator(source="auto", target="en").translate(text)
    except Exception:
        # Any failure (network blip, unsupported text, library issue) —
        # fail soft, return the original text rather than crashing the run.
        return text


def translate_extracted_fields(fields: dict, lang: str | None) -> dict:
    if not lang or lang == "en":
        return fields
    translatable_keys = ["product_name", "brand", "description", "ingredients_text", "ingredients"]
    out = dict(fields)
    for key in translatable_keys:
        if out.get(key):
            out[key] = translate_to_en(out[key], lang)
    return out