"""
Client for a self-hosted SearxNG instance. Free, no API key, returns results
across multiple backend engines regardless of the target page's language —
unlike driving google.com through a browser, which can silently localize/
redirect based on IP and mess with anchor scraping.

If SearxNG isn't running (Docker not started), every call here fails soft
and returns []. The pipeline treats that as "not available this run" and
falls back to the Playwright google.com / region-retailer search automatically.
"""

import httpx


async def searxng_search(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
    max_results: int = 8,
    timeout: float = 6.0,
) -> list[str]:
    url = f"{base_url.rstrip('/')}/search"
    # Quoting forces exact-phrase matching. An unquoted 13-digit number gets
    # loosely keyword-matched by most engines and returns unrelated popular
    # products — quoting cuts that noise dramatically.
    params = {"q": f'"{query}"', "format": "json"}
    try:
        resp = await client.get(url, params=params, timeout=timeout)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []

    results = data.get("results", [])
    urls = [r["url"] for r in results if r.get("url")]
    return urls[:max_results]


async def is_searxng_reachable(client: httpx.AsyncClient, base_url: str) -> bool:
    """
    Confirms JSON format is actually working, not just that the server
    responds — a misconfigured instance can return HTTP 200 with an HTML
    page instead of JSON, which would otherwise look "reachable" while
    silently never returning usable results.
    """
    try:
        resp = await client.get(f"{base_url.rstrip('/')}/search",
                                 params={"q": "test", "format": "json"}, timeout=3.0)
        if resp.status_code != 200:
            return False
        data = resp.json()  # raises if not actually JSON
        return "results" in data
    except Exception:
        return False