"""
Stage 0 — classify and validate every barcode BEFORE any network call.
No I/O in this module. Pure, fast, testable.
"""

from dataclasses import dataclass
from .gs1_prefixes import country_for_prefix


@dataclass
class BarcodeRecord:
    original: str
    barcode_type: str          # EAN13 / UPC_A / EAN8 / URL / GS1_DATAMATRIX / OTHER_NUMERIC / NON_NUMERIC / INVALID
    normalized_13: str | None  # normalized to 13-digit EAN form when applicable
    is_valid: bool
    gs1_country: str | None
    invalid_reason: str | None = None


def _ean_checksum_ok(digits: str) -> bool:
    """Standard GS1 mod-10 check digit validation for 8/12/13/14-digit codes."""
    if not digits.isdigit():
        return False
    body, check = digits[:-1], int(digits[-1])
    total = 0
    # Weighting alternates 3/1 from the rightmost digit of the body.
    for i, d in enumerate(reversed(body)):
        weight = 3 if i % 2 == 0 else 1
        total += int(d) * weight
    computed = (10 - (total % 10)) % 10
    return computed == check


def _normalize_to_13(digits: str, kind: str) -> str:
    if kind == "UPC_A":          # 12 digits -> prepend 0
        return "0" + digits
    if kind == "EAN8":
        return digits.zfill(13)  # not a true GTIN-13 conversion, but keeps a
                                  # consistent lookup key; original EAN8 is
                                  # still used for actual API calls
    return digits


def classify_barcode(raw: str) -> BarcodeRecord:
    value = (raw or "").strip()

    if not value:
        return BarcodeRecord(raw, "INVALID", None, False, None, "empty value")

    if value.startswith("http://") or value.startswith("https://"):
        return BarcodeRecord(raw, "URL", None, False, None, "QR/URL code, not a product barcode")

    if value.startswith("("):
        return BarcodeRecord(raw, "GS1_DATAMATRIX", None, False, None,
                              "GS1 Application Identifier code (pharma/cosmetic) — route to separate queue")

    if not value.isdigit():
        return BarcodeRecord(raw, "NON_NUMERIC", None, False, None,
                              "contains non-digit characters — likely internal SKU/RFID")

    length = len(value)

    if length == 13:
        kind = "EAN13"
    elif length == 12:
        kind = "UPC_A"
    elif length == 8:
        kind = "EAN8"
    elif length < 6:
        return BarcodeRecord(raw, "INVALID", None, False, None, "too short to be a valid barcode")
    else:
        return BarcodeRecord(raw, "OTHER_NUMERIC", None, False, None,
                              f"unusual length ({length} digits) — needs manual triage")

    checksum_ok = _ean_checksum_ok(value)
    normalized = _normalize_to_13(value, kind)
    country = country_for_prefix(normalized) if checksum_ok else None

    if not checksum_ok:
        return BarcodeRecord(raw, kind, normalized, False, None,
                              "failed GS1 check-digit validation — likely a scan error")

    return BarcodeRecord(raw, kind, normalized, True, country, None)
