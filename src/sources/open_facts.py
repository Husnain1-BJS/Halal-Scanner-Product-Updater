"""
Tier 1 — free, structured, no-scraping APIs. Always try these before touching
the web. Each function returns a normalized dict or None.
"""

import asyncio
import httpx

NORMALIZED_KEYS = ["product_name", "brand", "ingredients", "image_url",
                    "country_of_origin", "source_name", "source_url"]


def _empty():
    return {k: None for k in NORMALIZED_KEYS}


async def check_open_food_facts(client: httpx.AsyncClient, barcode: str) -> dict | None:
    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
    try:
        resp = await client.get(url, timeout=10)
        data = resp.json()
    except Exception:
        return None
    if data.get("status") != 1:
        return None
    p = data.get("product", {})
    out = _empty()
    out.update({
        "product_name": p.get("product_name"),
        "brand": p.get("brands"),
        "ingredients": p.get("ingredients_text"),
        "image_url": p.get("image_url"),
        "country_of_origin": p.get("countries"),
        "source_name": "OpenFoodFacts",
        "source_url": url,
    })
    return out


async def check_open_beauty_facts(client: httpx.AsyncClient, barcode: str) -> dict | None:
    url = f"https://world.openbeautyfacts.org/api/v2/product/{barcode}.json"
    try:
        resp = await client.get(url, timeout=10)
        data = resp.json()
    except Exception:
        return None
    if data.get("status") != 1:
        return None
    p = data.get("product", {})
    out = _empty()
    out.update({
        "product_name": p.get("product_name"),
        "brand": p.get("brands"),
        "ingredients": p.get("ingredients_text"),
        "image_url": p.get("image_url"),
        "country_of_origin": p.get("countries"),
        "source_name": "OpenBeautyFacts",
        "source_url": url,
    })
    return out


async def check_open_products_facts(client: httpx.AsyncClient, barcode: str) -> dict | None:
    url = f"https://world.openproductsfacts.org/api/v2/product/{barcode}.json"
    try:
        resp = await client.get(url, timeout=10)
        data = resp.json()
    except Exception:
        return None
    if data.get("status") != 1:
        return None
    p = data.get("product", {})
    out = _empty()
    out.update({
        "product_name": p.get("product_name"),
        "brand": p.get("brands"),
        "ingredients": p.get("ingredients_text"),
        "image_url": p.get("image_url"),
        "country_of_origin": p.get("countries"),
        "source_name": "OpenProductsFacts",
        "source_url": url,
    })
    return out


async def check_upcitemdb(client: httpx.AsyncClient, barcode: str) -> dict | None:
    """
    Free trial endpoint, no key, low daily cap (verify current limit — these
    change). Best-effort: treat failures/rate-limit responses as 'no data'
    rather than raising, so it never blocks the pipeline.
    """
    url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={barcode}"
    try:
        resp = await client.get(url, timeout=10)
        data = resp.json()
    except Exception:
        return None
    items = data.get("items") or []
    if not items:
        return None
    item = items[0]
    out = _empty()
    out.update({
        "product_name": item.get("title"),
        "brand": item.get("brand"),
        "ingredients": None,  # UPCitemdb rarely has ingredients — name/brand/image only
        "image_url": (item.get("images") or [None])[0],
        "country_of_origin": None,
        "source_name": "UPCitemdb",
        "source_url": url,
    })
    return out


# Ordered — cheapest/most-reliable first. Pipeline stops at first hit.
TIER1_CHECKS = [
    check_open_food_facts,
    check_open_beauty_facts,
    check_open_products_facts,
    check_upcitemdb,
]


async def run_tier1(client: httpx.AsyncClient, barcode: str) -> dict | None:
    """
    Runs all four free checks CONCURRENTLY (not one-after-another) — cuts
    Tier 1 latency down to whichever single check is slowest, instead of
    the sum of all four. Returns the highest-priority hit if multiple
    sources happen to have data.
    """
    results = await asyncio.gather(
        *(check(client, barcode) for check in TIER1_CHECKS),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception) or result is None:
            continue
        if result.get("product_name") or result.get("ingredients"):
            return result
    return None
