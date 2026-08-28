"""
Context-aware barcode verification.

OLD approach: barcode string appears ANYWHERE in the HTML -> pass.
Problem: a 13-digit number can appear in a URL slug, a cookie string, a
tracking pixel, an unrelated product's EAN on a listing page -> false pass.

NEW approach: score by WHERE the barcode appears:
  - In JSON-LD with @type:Product -> very strong (100pts)
  - In a GTIN/EAN/UPC meta/attribute near product signals -> strong (80pts)
  - In page text near price/product-title signals -> moderate (50pts)
  - Anywhere in raw HTML (old fallback) -> weak (20pts, only used if
    nothing stronger found, and min_score raised so this alone never passes)

Caller rejects if total score < config verification.min_score_to_accept (60).
That means a bare "barcode appears somewhere" (20pts) never passes alone --
it must be near real product context.
"""

import re
import json
from bs4 import BeautifulSoup

LD_JSON_PATTERN = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)

PRODUCT_SIGNALS = re.compile(
    r'price|product|ingredient|brand|manufacturer|ean|gtin|barcode|upc|sku',
    re.I,
)

_NON_DIGIT = re.compile(r'\D')


def _norm(code: str) -> str:
    return _NON_DIGIT.sub('', str(code or ''))


def _upc_variant(barcode: str) -> str | None:
    if len(barcode) == 13 and barcode.startswith('0'):
        return barcode[1:]
    if len(barcode) == 12:
        return '0' + barcode
    return None


def _in_json_ld(html: str, barcode: str, variant: str | None) -> int:
    """Highest confidence: barcode in a Product-typed JSON-LD block."""
    for block_str in LD_JSON_PATTERN.findall(html):
        if barcode not in block_str and (not variant or variant not in block_str):
            continue
        try:
            data = json.loads(block_str)
        except Exception:
            continue
        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get('@type') not in ('Product', 'product'):
                continue
            # Check GTIN fields directly
            for key in ('gtin13', 'gtin12', 'gtin', 'sku', 'mpn'):
                val = _norm(block.get(key, ''))
                if val and (val == _norm(barcode) or (variant and val == _norm(variant))):
                    return 100
            # Barcode in the block but not in a GTIN field -- still good
            if barcode in block_str or (variant and variant in block_str):
                return 80
    return 0


def _in_product_context(html: str, barcode: str, variant: str | None) -> int:
    """Moderate: barcode appears near price/product/ingredient words."""
    soup = BeautifulSoup(html, 'lxml')
    targets = [barcode] + ([variant] if variant else [])
    for target in targets:
        nodes = soup.find_all(string=re.compile(re.escape(target)))
        for node in nodes:
            # Check surrounding 500 chars for product signals
            parent_text = ''
            container = node.parent
            for _ in range(4):
                if container is None:
                    break
                parent_text = container.get_text(' ', strip=True)
                container = getattr(container, 'parent', None)
                if len(parent_text) > 50:
                    break
            if PRODUCT_SIGNALS.search(parent_text):
                return 60
    return 0


def _in_meta_attributes(html: str, barcode: str, variant: str | None) -> int:
    """Strong: barcode in a meta tag or data attribute suggesting GTIN/EAN."""
    gtin_attr = re.compile(
        r'(gtin|ean|upc|barcode|sku|product[-_]?id)["\'\s:=]+' +
        r'(?:' + re.escape(barcode) + (
            r'|' + re.escape(variant) if variant else '') + r')',
        re.I,
    )
    if gtin_attr.search(html):
        return 80
    return 0


def _anywhere(html: str, barcode: str, variant: str | None) -> int:
    """Weakest: barcode anywhere at all. Alone it never passes the 60pt bar."""
    if barcode in html or (variant and variant in html):
        return 20
    return 0


def verify_page(html: str, barcode: str) -> int:
    """
    Returns a confidence score. Score >= 60 (config verification.min_score)
    required before extracting data.
    """
    variant = _upc_variant(barcode)

    score = _in_json_ld(html, barcode, variant)
    if score >= 80:
        return score  # strong structured match, no need to keep checking

    score = max(score, _in_meta_attributes(html, barcode, variant))
    if score >= 80:
        return score

    score = max(score, _in_product_context(html, barcode, variant))
    if score >= 60:
        return score

    score = max(score, _anywhere(html, barcode, variant))
    return score  # likely 20 -> below threshold -> correctly rejected