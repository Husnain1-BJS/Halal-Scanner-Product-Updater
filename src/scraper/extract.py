"""
Extract product_name / brand / image / ingredients / halal-cert mentions from
an already-fetched, already-verified page. Priority: JSON-LD (GTIN-matched)
> localized DOM area near the barcode text > Open Graph (single-product pages
only) > generic HTML patterns. No AI anywhere in this file.

Key accuracy fix: pages listing MULTIPLE products (category/search pages)
used to silently return whichever Product block happened to be LAST in the
HTML, or the page-wide <title>/og:title -- neither is guaranteed to be the
product matching the barcode being searched. Now: if multiple Product blocks
exist, only the one whose GTIN matches the barcode is used. If none match,
extraction is scoped to just the DOM area around the barcode's own text
occurrence, instead of grabbing page-wide data that could belong to a
different, irrelevant product on the same page.
"""

import json
import re
from bs4 import BeautifulSoup

E_NUMBER_PATTERN = re.compile(r"\bE[\s-]?\d{3}[a-z]?\b", re.I)
HALAL_CERT_PATTERN = re.compile(
    r"\b(halal|JAKIM|MUI|IFANCA|HMC|HFA|ESMA)\b", re.I
)

INGREDIENT_SECTION_HINTS = [
    "ingredient", "ingredients", "composition", "inci",
]

INGREDIENT_BLOCK_BLACKLIST = [
    "disclaimer", "report this product", "incomplete or incorrect",
    "moderator", "we work to ensure", "if the information does not match",
    "collaborative database", "contribution is useful",
]

XML_SITEMAP_MARKERS = ["<?xml", "<urlset", "<sitemapindex"]

_NON_DIGIT = re.compile(r"\D")


def _norm_code(code) -> str:
    return _NON_DIGIT.sub("", str(code or ""))


def looks_like_non_html_content(raw: str) -> bool:
    head = raw[:300].strip().lower()
    return any(marker in head for marker in XML_SITEMAP_MARKERS)


def _product_blocks_from_json_ld(soup: BeautifulSoup) -> list[dict]:
    """All Product blocks on the page, as raw dicts."""
    blocks = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for block in candidates:
            if isinstance(block, dict) and block.get("@type") in ("Product", "product"):
                blocks.append(block)
    return blocks


def _fields_from_block(block: dict) -> dict:
    out = {"product_name": block.get("name"), "description": block.get("description")}
    brand = block.get("brand")
    if isinstance(brand, dict):
        out["brand"] = brand.get("name")
    elif isinstance(brand, str):
        out["brand"] = brand
    image = block.get("image")
    if isinstance(image, list) and image:
        out["image_url"] = image[0]
    elif isinstance(image, str):
        out["image_url"] = image
    out["gtin"] = block.get("gtin13") or block.get("gtin") or block.get("gtin12")
    return out


def _from_json_ld(soup: BeautifulSoup, barcode: str) -> tuple[dict, bool]:
    """
    Returns (fields, is_ambiguous_multi_product).
    is_ambiguous_multi_product=True means: multiple products were on the
    page and NONE of their GTINs matched -- caller should NOT fall back to
    page-wide data (og:title etc), since that could belong to any of them.
    """
    blocks = _product_blocks_from_json_ld(soup)
    if not blocks:
        return {}, False

    if len(blocks) == 1:
        return _fields_from_block(blocks[0]), False

    # Multiple products on this page -- only trust an exact GTIN match.
    target = _norm_code(barcode)
    for block in blocks:
        fields = _fields_from_block(block)
        if fields.get("gtin") and _norm_code(fields["gtin"]) == target:
            return fields, False

    return {}, True  # ambiguous: several products, none matched


def _from_open_graph(soup: BeautifulSoup) -> dict:
    out = {}
    mapping = {
        "og:title": "product_name",
        "og:image": "image_url",
        "og:description": "description",
        "product:brand": "brand",
    }
    for prop, key in mapping.items():
        tag = soup.find("meta", property=prop)
        if tag and tag.get("content"):
            out.setdefault(key, tag["content"])
    return out


def _find_ingredient_block(soup: BeautifulSoup) -> str | None:
    for hint in INGREDIENT_SECTION_HINTS:
        for el in soup.find_all(string=re.compile(hint, re.I)):
            if not el or not el.parent:
                continue
            container = el.find_parent(["div", "section", "p", "li"])
            if not container:
                continue
            text = container.get_text(" ", strip=True)
            lowered = text.lower()
            if len(text) <= 20 or len(text) > 3000:
                continue
            if any(bad in lowered for bad in INGREDIENT_BLOCK_BLACKLIST):
                continue
            if text.count(",") < 1 and text.count("،") < 1:
                continue
            return text
    return None


def _extract_near_barcode(soup: BeautifulSoup, barcode: str) -> dict:
    """
    Fallback for multi-product pages with no JSON-LD: find the smallest
    container (product card) that actually holds the barcode text, and
    pull name/image/ingredients from WITHIN that container only -- not
    page-wide -- so an irrelevant neighboring product on the same listing
    page can't get mixed in.
    """
    node = soup.find(string=re.compile(re.escape(barcode)))
    if not node:
        return {}
    # walk up to a plausible "product card" container, not the whole page
    container = node
    for _ in range(6):
        container = container.parent if hasattr(container, "parent") else None
        if container is None:
            return {}
        tag_name = getattr(container, "name", "")
        if tag_name in ("div", "li", "article", "section") and \
                len(container.get_text(" ", strip=True)) < 4000:
            break
    if container is None or not hasattr(container, "find"):
        return {}

    out = {}
    heading = container.find(["h1", "h2", "h3", "h4"])
    if heading:
        out["product_name"] = heading.get_text(" ", strip=True)
    img = container.find("img")
    if img and img.get("src"):
        out["image_url"] = img["src"]
    fallback_ing = _find_ingredient_block(container)
    if fallback_ing:
        out["ingredients_text"] = fallback_ing
    return out


def extract_product_data(html: str, barcode: str = "") -> dict:
    if looks_like_non_html_content(html):
        return {"e_numbers_found": [], "halal_cert_mentions": []}

    soup = BeautifulSoup(html, "lxml")

    json_ld_fields, ambiguous = _from_json_ld(soup, barcode)

    if ambiguous:
        # Multiple products on the page, couldn't isolate ours via GTIN --
        # do NOT use page-wide OG tags (could be any of them). Scope
        # extraction to the DOM area actually containing our barcode.
        data = _extract_near_barcode(soup, barcode) if barcode else {}
    elif json_ld_fields:
        data = json_ld_fields
    else:
        # Single-product page (or no structured data at all) -- page-wide
        # OG tags are safe to use here since there's only one product.
        data = _from_open_graph(soup)

    if not data.get("ingredients_text"):
        fallback = _find_ingredient_block(soup) if not ambiguous else None
        if fallback:
            data["ingredients_text"] = fallback

    full_text = soup.get_text(" ", strip=True)
    data["e_numbers_found"] = sorted(set(E_NUMBER_PATTERN.findall(full_text)))
    data["halal_cert_mentions"] = sorted(set(HALAL_CERT_PATTERN.findall(full_text)))

    return data