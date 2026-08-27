"""
Before trusting any scraped page, confirm the barcode is actually ON it.
This is the deterministic, no-AI replacement for 'is this the right product'.
"""

import re

LD_JSON_PATTERN = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def _upc_variant(barcode: str) -> str | None:
    """Cross-check the alternate EAN13/UPC-A form (leading-zero difference)."""
    if len(barcode) == 13 and barcode.startswith("0"):
        return barcode[1:]
    if len(barcode) == 12:
        return "0" + barcode
    return None


def verify_page(html: str, barcode: str) -> int:
    """
    Returns a confidence score. Compare against config.yaml
    verification.min_score_to_accept (default 60) before extracting data.
    """
    score = 0
    variant = _upc_variant(barcode)

    if barcode in html:
        score += 60
    if variant and variant in html:
        score += 60

    for block in LD_JSON_PATTERN.findall(html):
        if barcode in block or (variant and variant in block):
            score += 100
            break  # one strong structured-data match is enough

    return score
