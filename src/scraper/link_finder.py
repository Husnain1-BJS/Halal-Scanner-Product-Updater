"""
Fixes the 'search returned a homepage, not a product page' problem.
Pure functions — no network calls here, operate on already-fetched HTML.
"""

import re
from urllib.parse import urljoin, urlparse, parse_qs

PRODUCT_PATH_MARKERS = [
    r"/p/", r"/product/", r"/products/", r"/dp/",
    r"/item/", r"/pd/", r"\.html$", r"/prod/", r"/catalog/product",
    r"/produto/", r"/produkt/", r"/prodotto/", r"/produit/",  # PT/DE/IT/FR
    r"/urun/", r"/tuote/",  # TR/FI
]

HREF_PATTERN = re.compile(r'href=["\'](.*?)["\']', re.I)

# Google wraps real destination URLs as /url?q=<target>&... -- without
# unwrapping this, every legit result link is invisible to path/barcode
# matching, since the visible href is just a Google-internal redirect.
GOOGLE_REDIRECT_HOSTS = {"www.google.com", "google.com"}


def is_likely_homepage(url: str) -> bool:
    path = urlparse(url).path.strip("/")
    return path == "" or len(path.split("/")) <= 1


def _unwrap_google_redirect(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc in GOOGLE_REDIRECT_HOSTS and parsed.path == "/url":
        qs = parse_qs(parsed.query)
        target = qs.get("q") or qs.get("url")
        if target:
            return target[0]
    return url


def find_product_links(html: str, base_url: str, barcode: str) -> list[tuple[int, str]]:
    candidates: dict[str, int] = {}
    for href in HREF_PATTERN.findall(html):
        full_url = urljoin(base_url, href)
        full_url = _unwrap_google_redirect(full_url)
        score = 0
        if barcode in full_url:
            score += 100
        if any(re.search(marker, full_url, re.I) for marker in PRODUCT_PATH_MARKERS):
            score += 50
        if score > 0:
            candidates[full_url] = max(candidates.get(full_url, 0), score)
    ranked = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)
    return [(score, url) for url, score in ranked]


def domain_of(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc