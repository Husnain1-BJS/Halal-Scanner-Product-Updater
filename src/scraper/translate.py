"""
Priority 4 -- translation based on ACTUAL extracted text content, not the
<html lang=""> attribute (often missing/wrong on Asian e-commerce sites --
many pages declare lang="en" while body content is entirely non-English).
"""

import re
from deep_translator import GoogleTranslator

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0  # deterministic results
except ImportError:
    detect = None


def detect_lang_from_text(text: str) -> str | None:
    """Detect language from the ACTUAL content, not an HTML attribute."""
    if not text or len(text.strip()) < 10 or detect is None:
        return None
    try:
        return detect(text)
    except Exception:
        return None


def detect_lang_from_html(html: str) -> str | None:
    """Kept for backward compatibility -- prefer detect_lang_from_text when
    you have real extracted content available; this is a weaker fallback."""
    match = re.search(r'<html[^>]+lang=["\']([a-zA-Z\-]{2,5})', html, re.I)
    return match.group(1)[:2].lower() if match else None


def translate_text(text: str, source_lang: str | None) -> str:
    if not text or not source_lang or source_lang == "en":
        return text
    try:
        return GoogleTranslator(source=source_lang, target="en").translate(text)
    except Exception:
        return text  # fail soft -- never crash the pipeline over translation


def translate_extracted_fields(fields: dict, lang: str | None = None) -> dict:
    """
    Detects language from the actual field content (product_name +
    ingredients combined) if not already provided, then translates every
    text field consistently. This catches cases where the page's <html
    lang> tag lied but the real content is non-English.
    """
    keys = ["product_name", "brand", "description", "ingredients_text", "ingredients"]
    combined = " ".join(str(fields.get(k, "") or "") for k in keys)

    if lang is None:
        lang = detect_lang_from_text(combined)
    if not lang or lang == "en":
        return fields

    out = dict(fields)
    for key in keys:
        if out.get(key):
            out[key] = translate_text(out[key], lang)
    out["_detected_language"] = lang
    return out