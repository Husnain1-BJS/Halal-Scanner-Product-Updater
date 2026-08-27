"""
Most product pages don't need JS rendering to expose their JSON-LD/OG data —
that structured data is usually server-rendered even on JS-heavy sites, since
it's meant for search engine crawlers, not just humans. So: try a plain httpx
GET first (fast, cheap, high concurrency possible). Only pay for a full
Playwright browser page when httpx genuinely comes back empty-handed.
"""

import re
import httpx

BLOCK_INDICATORS = [
    "pardon our interruption", "are you a robot", "unusual traffic",
    "captcha", "access denied", "403 forbidden",
    "before you continue to google search",  # EU/EEA cookie-consent wall
    "consent.google.com",
]

# If the raw HTML has none of these, it's very likely a JS-rendered shell
# that needs a real browser to populate.
STRUCTURED_DATA_HINTS = [
    r'application/ld\+json', r'og:title', r'og:image', r'gtin',
]

from ..utils import random_user_agent

def _headers():
    return {"User-Agent": random_user_agent(), "Accept-Language": "en-US,en;q=0.9"}


def _looks_js_rendered(html: str) -> bool:
    if len(html) < 2000:  # suspiciously small = likely an empty JS shell
        return True
    return not any(re.search(hint, html, re.I) for hint in STRUCTURED_DATA_HINTS)


BLOCKED_STATUS_CODES = {401, 403, 429, 503}  # add others you see in logs

async def fetch_httpx(client: httpx.AsyncClient, url: str, timeout: float) -> tuple[str, bool, bool]:
    """
    Returns (html, was_blocked, needs_js_fallback).
    """
    try:
        resp = await client.get(url, headers=_headers(), timeout=timeout)
        html = resp.text
    except Exception:
        return "", False, True  # couldn't fetch at all -> let Playwright try properly

    # Check the status code FIRST — a 403/429/etc. is a block regardless of
    # what the body text says, and some anti-bot pages return a 200 with a
    # deceptively normal-looking shell, so status and body checks are both needed.
    if resp.status_code in BLOCKED_STATUS_CODES:
        return html, True, False

    if resp.status_code >= 400:
        # Any other 4xx/5xx: not necessarily a "block", but definitely not
        # usable page content — don't let it fall through to the JS-render
        # heuristic and get treated as a legit small page.
        return html, False, True  # let Playwright retry properly, might be transient

    lowered = html.lower()
    blocked = any(indicator in lowered for indicator in BLOCK_INDICATORS)
    if blocked:
        return html, True, False

    return html, False, _looks_js_rendered(html)

async def fetch_smart(
    http_client: httpx.AsyncClient,
    browser_page,
    url: str,
    httpx_timeout: float,
    playwright_timeout_ms: int,
) -> tuple[str, bool, str]:
    """
    Returns (html, was_blocked, method_used) where method_used is
    'httpx' or 'playwright' — useful for logging/tuning later.
    """
    html, blocked, needs_js = await fetch_httpx(http_client, url, httpx_timeout)
    if blocked:
        return html, True, "httpx"
    if not needs_js:
        return html, False, "httpx"

    # Fallback: full browser render
    try:
        await browser_page.goto(url, timeout=playwright_timeout_ms, wait_until="domcontentloaded")
        html = await browser_page.content()
    except Exception:
        return "", False, "playwright_failed"

    lowered = html.lower()
    blocked = any(indicator in lowered for indicator in BLOCK_INDICATORS)
    return html, blocked, "playwright"