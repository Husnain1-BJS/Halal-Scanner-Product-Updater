"""
Priority 3 -- Firecrawl as a LAST-RESORT scrape fallback, only when httpx +
Playwright both fail (Cloudflare-protected sites etc). Free tier is a
ONE-TIME 500-1000 credit grant, NOT monthly -- so this must stay a rare
fallback, never a primary source, or you burn it in one batch run.

Get a free key (no card): https://www.firecrawl.dev -> sign up -> API key.
Add it to config.yaml under firecrawl_api_key. Leave blank to disable --
every call here fails soft to None if no key is set.
"""

import httpx


async def firecrawl_scrape(client: httpx.AsyncClient, url: str, api_key: str) -> str | None:
    if not api_key:
        return None
    try:
        resp = await client.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"url": url, "formats": ["html"]},
            timeout=25,
        )
        data = resp.json()
    except Exception:
        return None
    if not data.get("success"):
        return None
    return data.get("data", {}).get("html")