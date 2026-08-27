"""
Orchestrates the full per-barcode flow:
  classify -> Tier1 free APIs (parallel) -> Tier2 sequential search fallback
  (SearxNG, THEN region-routed retailer search, only moving to the next
  stage if nothing in the current stage actually verifies) -> hybrid
  httpx/Playwright fetch -> verify -> translate -> extract -> checkpoint save

Key correctness fixes vs the earlier version:
  - Tier 2 is a TRUE fallback: getting some search results is not the same
    as getting the RIGHT result. Each stage's candidates are tried in full;
    only an empty-handed stage moves on to the next one.
  - A page that's still a listing/search-results page after the homepage
    link-resolution attempt is REJECTED outright, not extracted from.
  - Confidence tiers: a JSON-LD/GTIN-matched page is "high" confidence and
    always accepted. A weaker text-match page is "low" confidence and is
    only accepted if it actually yielded usable data.
  - Candidate URLs are deduped before trying.
  - Non-HTML content (sitemap.xml etc.) is rejected before extraction.
  - Tier 2b's search-page fetch now goes through fetch_smart() (httpx-first,
    Playwright-fallback) instead of always using a full browser — faster
    and lighter, same reasoning as every other fetch in the pipeline.
  - Every fetch is now gated by a per-domain concurrency limiter, on top of
    the existing rate limiter, so multiple concurrent workers can't all
    land on the same domain in the same instant.
"""

import httpx

from .classify import classify_barcode
from .sources.open_facts import run_tier1
from .sources.region_routing import sources_for_country, DEPRIORITIZED_DOMAINS
from .sources.searxng import searxng_search, is_searxng_reachable
from .scraper.link_finder import is_likely_homepage, find_product_links, domain_of
from .scraper.verify import verify_page
from .scraper.extract import extract_product_data
from .scraper.translate import detect_lang_from_html, translate_extracted_fields, detect_lang_from_text
from .scraper.fetch import fetch_smart

HIGH_CONFIDENCE_SCORE = 100  # JSON-LD/GTIN structured match


def _found_row(record, fields, source_url, source_name, score, scan_count,
               confidence, e_numbers=None, cert_mentions=None):
    return {
        "barcode": record.original,
        "barcode_type": record.barcode_type,
        "gs1_country": record.gs1_country,
        "product_name": fields.get("product_name"),
        "brand": fields.get("brand"),
        "ingredients": fields.get("ingredients") or fields.get("ingredients_text"),
        "e_numbers_found": e_numbers or [],
        "image_url": fields.get("image_url"),
        "country_of_origin": fields.get("country_of_origin") or record.gs1_country,
        "halal_cert_mentions": cert_mentions or [],
        "source_url": source_url,
        "source_name": source_name,
        "verification_score": score,
        "confidence": confidence,   # "high" or "low" — see module docstring
        "scan_count": scan_count,
    }


def _dedupe(urls: list[str]) -> list[str]:
    seen = set()
    out = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _has_usable_data(fields: dict) -> bool:
    has_name = bool(fields.get("product_name"))
    has_ingredients = bool(fields.get("ingredients") or fields.get("ingredients_text"))
    has_image = bool(fields.get("image_url"))
    return has_name and (has_ingredients or has_image)


async def _fetch_with_domain_limit(
    http_client, browser_page, url, config, domain_limiter,
):
    """Wraps fetch_smart() with the per-domain concurrency cap, if provided."""
    domain = domain_of(url)
    if domain_limiter is not None:
        async with domain_limiter.limit(domain):
            return await fetch_smart(
                http_client, browser_page, url,
                config["httpx_timeout_seconds"], config["page_timeout_ms"],
            )
    return await fetch_smart(
        http_client, browser_page, url,
        config["httpx_timeout_seconds"], config["page_timeout_ms"],
    )


async def _try_candidate_url(
    candidate_url: str,
    barcode: str,
    http_client: httpx.AsyncClient,
    browser_page,
    rate_limiter,
    circuit_breaker,
    config: dict,
    logger,
    domain_limiter=None,
) -> dict | None:
    """Fetch + verify + extract a single candidate URL. Returns fields dict or None."""
    domain = domain_of(candidate_url)

    if domain in DEPRIORITIZED_DOMAINS:
        return None
    if await circuit_breaker.is_open(domain):
        return None

    await rate_limiter.wait(domain)

    html, blocked, method = await _fetch_with_domain_limit(
        http_client, browser_page, candidate_url, config, domain_limiter,
    )

    if blocked or not html:
        await circuit_breaker.record_result(domain, success=False)
        return None

    # If it's a homepage/search-results shell, try to resolve to a real
    # product link. If that fails, REJECT this candidate outright — do not
    # fall back to extracting from the listing page itself.
    still_unresolved = is_likely_homepage(candidate_url)
    if still_unresolved:
        sub_candidates = find_product_links(html, candidate_url, barcode)
        if sub_candidates:
            better_url = sub_candidates[0][1]
            better_domain = domain_of(better_url)
            if not await circuit_breaker.is_open(better_domain) and better_domain not in DEPRIORITIZED_DOMAINS:
                await rate_limiter.wait(better_domain)
                html2, blocked2, _ = await _fetch_with_domain_limit(
                    http_client, browser_page, better_url, config, domain_limiter,
                )
                if html2 and not blocked2:
                    html = html2
                    candidate_url = better_url
                    domain = better_domain
                    still_unresolved = False
        if still_unresolved:
            return None  # couldn't resolve to an actual product page — reject

    score = verify_page(html, barcode)
    if score < config["verification"]["min_score_to_accept"]:
        await circuit_breaker.record_result(domain, success=False)
        return None

    lang = detect_lang_from_html(html)
    fields = extract_product_data(html, barcode)
    fields = translate_extracted_fields(fields, lang)

    confidence = "high" if score >= HIGH_CONFIDENCE_SCORE else "low"
    if confidence == "low" and not _has_usable_data(fields):
        # Verified the barcode is technically on the page, but nothing
        # usable came out of it — reject and keep searching rather than
        # writing an empty row.
        await circuit_breaker.record_result(domain, success=False)
        return None

    await circuit_breaker.record_result(domain, success=True)

    fields["_source_url"] = candidate_url
    fields["_source_name"] = domain
    fields["_score"] = score
    fields["_confidence"] = confidence
    return fields


async def _try_candidates(
    candidate_urls: list[str],
    barcode: str,
    http_client, browser_page, rate_limiter, circuit_breaker, config, logger,
    attempted_sources: list[str],
    domain_limiter=None,
) -> dict | None:
    for candidate_url in _dedupe(candidate_urls):
        attempted_sources.append(candidate_url)
        fields = await _try_candidate_url(
            candidate_url, barcode, http_client, browser_page,
            rate_limiter, circuit_breaker, config, logger, domain_limiter,
        )
        if fields:
            return fields
    return None


async def process_one_barcode(
    raw_barcode: str,
    scan_count,
    http_client: httpx.AsyncClient,
    browser_page,
    rate_limiter,
    config: dict,
    logger,
    circuit_breaker=None,
    domain_limiter=None,
) -> tuple[str, dict]:
    """
    Returns (status, row) where status is 'found' | 'invalid' | 'not_found'.
    """
    record = classify_barcode(raw_barcode)

    if not record.is_valid:
        return "invalid", {
            "original_value": record.original,
            "detected_type": record.barcode_type,
            "reason": record.invalid_reason,
            "scan_count": scan_count,
        }

    barcode = record.normalized_13 or record.original

    if circuit_breaker is None:
        from .utils import DomainCircuitBreaker
        circuit_breaker = DomainCircuitBreaker(failure_threshold=999999, enabled=False)

    # ---- Tier 1: free structured APIs (parallel) ----
    tier1_result = await run_tier1(http_client, barcode)
    if tier1_result:
        text_for_lang = " ".join(filter(None, [
            tier1_result.get("product_name"), tier1_result.get("ingredients"),
        ]))
        lang = detect_lang_from_text(text_for_lang) if text_for_lang else None
        tier1_result = translate_extracted_fields(tier1_result, lang)
        return "found", _found_row(
            record, tier1_result, tier1_result.get("source_url"),
            tier1_result.get("source_name"), 100, scan_count, confidence="high",
        )

    attempted_sources: list[str] = []

    # ---- Tier 2a: SearxNG (if reachable) — tried in FULL before falling back ----
    searxng_cfg = config.get("search", {})
    if searxng_cfg.get("searxng_enabled") and await is_searxng_reachable(http_client, searxng_cfg["searxng_url"]):
        searxng_urls = await searxng_search(
            http_client, searxng_cfg["searxng_url"], barcode,
            max_results=searxng_cfg.get("searxng_max_results", 8),
        )
        attempted_sources.append(f"searxng:{barcode}")
        fields = await _try_candidates(
            searxng_urls, barcode, http_client, browser_page,
            rate_limiter, circuit_breaker, config, logger, attempted_sources,
            domain_limiter,
        )
        if fields:
            return "found", _found_row(
                record, fields, fields["_source_url"], fields["_source_name"],
                fields["_score"], scan_count, fields["_confidence"],
                e_numbers=fields.get("e_numbers_found", []),
                cert_mentions=fields.get("halal_cert_mentions", []),
            )

    # ---- Tier 2b: region-routed retailer search (includes global Google
    # fallback as its last entry) — only reached if Tier 2a found nothing.
    # Search-page fetch now uses the same fast hybrid fetcher as everything
    # else, instead of always forcing a full Playwright browser load. ----
    region_candidate_urls: list[str] = []
    for search_url_template in sources_for_country(record.gs1_country):
        search_url = search_url_template.format(barcode=barcode)
        domain = domain_of(search_url)
        if domain in DEPRIORITIZED_DOMAINS or await circuit_breaker.is_open(domain):
            continue
        await rate_limiter.wait(domain)
        try:
            html, blocked, _ = await _fetch_with_domain_limit(
                http_client, browser_page, search_url, config, domain_limiter,
            )
            if blocked or not html:
                await circuit_breaker.record_result(domain, success=False)
                continue
            page_links = find_product_links(html, search_url, barcode)
            region_candidate_urls.extend(u for _, u in page_links[:5])
            # The search/listing URL itself is intentionally NOT added as a
            # candidate — _try_candidate_url rejects unresolved listing
            # pages anyway, and this avoids wasting a fetch confirming that.
        except Exception as e:
            logger.info(f"[{barcode}] search fetch failed for {search_url}: {e}")
            await circuit_breaker.record_result(domain, success=False)
            continue

    fields = await _try_candidates(
        region_candidate_urls, barcode, http_client, browser_page,
        rate_limiter, circuit_breaker, config, logger, attempted_sources,
        domain_limiter,
    )
    if fields:
        return "found", _found_row(
            record, fields, fields["_source_url"], fields["_source_name"],
            fields["_score"], scan_count, fields["_confidence"],
            e_numbers=fields.get("e_numbers_found", []),
            cert_mentions=fields.get("halal_cert_mentions", []),
        )

    return "not_found", {
        "barcode": record.original,
        "barcode_type": record.barcode_type,
        "gs1_country": record.gs1_country,
        "sources_attempted": attempted_sources,
        "scan_count": scan_count,
    }