"""
Tier 3 — region-specific retailer search, keyed by GS1 country (from
gs1_prefixes.country_for_prefix). Each entry is a site-search URL template
using {barcode}. Expand this dict as you discover which domains actually
resolve your products; that's expected and normal.
"""

REGION_SOURCES = {
    "Japan": [
        "https://www.google.com/search?q={barcode}+site:kakaku.com",
        "https://www.amazon.co.jp/s?k={barcode}",
    ],
    "Malaysia": [
        "https://shopee.com.my/search?keyword={barcode}",
        "https://www.lazada.com.my/catalog/?q={barcode}",
    ],
    "Indonesia": [
        "https://www.tokopedia.com/search?st=product&q={barcode}",
        "https://shopee.co.id/search?keyword={barcode}",
        # NOTE: BPOM's public checker (cekbpom.pom.go.id) is a JS SPA with no
        # documented query-param search URL — removed rather than hitting a
        # static homepage every time. Revisit if BPOM publishes a real API.
    ],
    "Thailand": [
        "https://shopee.co.th/search?keyword={barcode}",
        "https://www.lazada.co.th/catalog/?q={barcode}",
    ],
    "South Korea": [
        "https://www.coupang.com/np/search?q={barcode}",
        "https://global.oliveyoung.com/display/search?query={barcode}",
    ],
    "China": [
        "https://search.jd.com/Search?keyword={barcode}",
        "https://s.taobao.com/search?q={barcode}",
    ],
    "Vietnam": [
        "https://tiki.vn/search?q={barcode}",
        "https://shopee.vn/search?keyword={barcode}",
    ],
    "Saudi Arabia": [
        "https://www.noon.com/saudi-en/search/?q={barcode}",
        "https://www.amazon.sa/s?k={barcode}",
    ],
    "United Arab Emirates": [
        "https://www.noon.com/uae-en/search/?q={barcode}",
        "https://www.amazon.ae/s?k={barcode}",
    ],
    "United Kingdom": [
        "https://www.tesco.com/groceries/en-GB/search?query={barcode}",
        "https://www.amazon.co.uk/s?k={barcode}",
    ],
    "India": [
        "https://www.bigbasket.com/ps/?q={barcode}",
        "https://www.amazon.in/s?k={barcode}",
    ],
    "Italy": [
        "https://www.amazon.it/s?k={barcode}",
    ],
    "Germany": [
        "https://www.amazon.de/s?k={barcode}",
    ],
    "Spain": [
        "https://www.amazon.es/s?k={barcode}",
    ],
    "United States / Canada": [
        "https://www.walmart.com/search?q={barcode}",
        "https://www.target.com/s?searchTerm={barcode}",
    ],
    "Russia": [
        "https://www.ozon.ru/search/?text={barcode}",
        "https://www.wildberries.ru/catalog/0/search.aspx?search={barcode}",
    ],
    "Portugal": [
        "https://www.continente.pt/pesquisa/?q={barcode}",
        "https://www.worten.pt/search?q={barcode}",
    ],
    "France": [
        "https://www.carrefour.fr/s?q={barcode}",
    ],
    "Poland": [
        "https://www.allegro.pl/listing?string={barcode}",
    ],
}

# Global fallback if country not in the table above, or all region sources miss.
GLOBAL_FALLBACK = [
    "https://www.google.com/search?q={barcode}",
]

# Domains that reliably show bot-block pages — tried last, abandoned fast on
# any 403 / interstitial match rather than retried.
DEPRIORITIZED_DOMAINS = {"ebay.com", "amazon.com", "amazon.co.uk", "amazon.de"}


def sources_for_country(country: str | None) -> list[str]:
    if country and country in REGION_SOURCES:
        return REGION_SOURCES[country] + GLOBAL_FALLBACK
    return GLOBAL_FALLBACK