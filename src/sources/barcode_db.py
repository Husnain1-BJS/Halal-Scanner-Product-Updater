"""
Priority 2 -- exact barcode lookup databases, tried BEFORE any search/scrape.
These return structured product data directly for a specific barcode --
far more reliable than search engines, which rank by keyword relevance and
can surface unrelated pages that merely contain the number somewhere.
"""

import httpx

NORMALIZED_KEYS = ["product_name", "brand", "ingredients", "image_url",
                    "country_of_origin", "source_name", "source_url"]


def _empty():
    return {k: None for k in NORMALIZED_KEYS}


async def check_digit_eyes(client: httpx.AsyncClient, barcode: str, app_key: str = "", app_id: str = "") -> dict | None:
    """
    Free tier lookup. Sign up at digit-eyes.com/register for a free app_key
    + app_id (no card required). Without credentials this call is skipped.
    """
    if not app_key or not app_id:
        return None
    url = "https://www.digit-eyes.com/gtin/v2_0/"
    params = {"upcCode": barcode, "field_names": "description,brand,ingredients,image",
              "app_key": app_key, "signature": app_id, "language": "en"}
    try:
        resp = await client.get(url, params=params, timeout=8)
        data = resp.json()
    except Exception:
        return None
    if not data.get("description"):
        return None
    out = _empty()
    out.update({
        "product_name": data.get("description"),
        "brand": data.get("brand"),
        "ingredients": data.get("ingredients"),
        "image_url": data.get("image"),
        "source_name": "DigitEyes",
        "source_url": url,
    })
    return out


async def check_go_upc(client: httpx.AsyncClient, barcode: str, api_key: str = "") -> dict | None:
    """Free tier available at go-upc.com/api -- requires a free API key."""
    if not api_key:
        return None
    url = f"https://go-upc.com/api/v1/code/{barcode}"
    try:
        resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=8)
        data = resp.json()
    except Exception:
        return None
    product = data.get("product") or {}
    if not product.get("name"):
        return None
    out = _empty()
    out.update({
        "product_name": product.get("name"),
        "brand": product.get("brand"),
        "ingredients": None,
        "image_url": product.get("imageUrl"),
        "source_name": "GoUPC",
        "source_url": url,
    })
    return out


async def run_barcode_db_tier(client: httpx.AsyncClient, barcode: str, config: dict) -> dict | None:
    """
    Tries all configured barcode databases in parallel. Add your free API
    keys to config.yaml under barcode_databases: -- any without a key is
    skipped automatically, no error.
    """
    import asyncio
    creds = config.get("barcode_databases", {})
    results = await asyncio.gather(
        check_digit_eyes(client, barcode, creds.get("digit_eyes_app_key", ""),
                          creds.get("digit_eyes_app_id", "")),
        check_go_upc(client, barcode, creds.get("go_upc_api_key", "")),
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, dict) and r.get("product_name"):
            return r
    return None