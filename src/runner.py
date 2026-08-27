"""
Shared orchestration logic used by main.py (CLI) and streamlit_app.py.
Also exposes lookup_single_barcode() for one-off checks/re-checks, used by
both the CLI's --barcode flag and the Streamlit sidebar lookup box.
"""

import asyncio
import csv
import time
from pathlib import Path

import httpx

from .storage import Checkpoint
from .writer import write_all, write_summary
from .utils import setup_logging, DomainRateLimiter, DomainCircuitBreaker, DomainConcurrencyLimiter
from .pipeline import process_one_barcode
from .scraper.browser import Browser


def read_input_csv(path: str, sample: int | None = None) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames_lower = {name.lower(): name for name in reader.fieldnames or []}
        barcode_col = None
        for alias in ["barcode", "code", "ean", "upc"]:
            if alias in fieldnames_lower:
                barcode_col = fieldnames_lower[alias]
                break
        if not barcode_col:
            raise ValueError(
                f"No barcode-like column found. Columns present: {reader.fieldnames}"
            )
        rows = []
        for row in reader:
            rows.append({
                "barcode": row.get(barcode_col, "").strip(),
                "scan_count": row.get("ScanCount") or row.get("scan_count"),
            })
    if sample:
        rows = rows[:sample]
    return rows


async def run_pipeline(
    input_csv_path: str,
    config: dict,
    sample: int | None = None,
    fresh: bool = False,
    headless: bool = True,
    progress_callback=None,   # called as progress_callback(completed, total)
) -> dict:
    """
    Runs the full pipeline and returns the summary dict. Also writes the
    three output CSVs and run_summary.json as a side effect.
    """
    logger = setup_logging(config["paths"]["log_file"])

    if fresh:
        Path(config["paths"]["checkpoint_db"]).unlink(missing_ok=True)

    checkpoint = Checkpoint(config["paths"]["checkpoint_db"])
    rate_limiter = DomainRateLimiter(
        config["rate_limit"]["default_seconds_between_requests"],
        config["rate_limit"]["per_domain_overrides"],
    )
    circuit_breaker = DomainCircuitBreaker(
        failure_threshold=config.get("circuit_breaker", {}).get("failure_threshold", 4),
        enabled=config.get("circuit_breaker", {}).get("enabled", True),
        cooldown_seconds=config.get("circuit_breaker", {}).get("cooldown_seconds", 300),
    )
    domain_limiter = DomainConcurrencyLimiter(
        max_per_domain=config.get("max_concurrent_per_domain", 2),
    )

    rows = read_input_csv(input_csv_path, sample)
    pending = [r for r in rows if not checkpoint.already_done(r["barcode"])]
    total = len(pending)
    logger.info(f"Total rows: {len(rows)} | already done: {len(rows) - total} | pending: {total}")

    browser = Browser(headless=headless)
    await browser.start()

    browser_semaphore = asyncio.Semaphore(config["concurrency"])
    http_client = httpx.AsyncClient(follow_redirects=True)

    completed = 0
    completed_lock = asyncio.Lock()

    async def worker(row):
        # EVERYTHING in here is caught -- a single bad page/browser crash
        # must never escape and kill the whole batch via gather().
        nonlocal completed
        page = None
        try:
            async with browser_semaphore:
                if not await browser.is_alive():
                    logger.info("Browser not alive -- restarting.")
                    await browser.restart()
                try:
                    page = await browser.new_page()
                except Exception as e:
                    logger.info(f"new_page failed, restarting browser: {e}")
                    await browser.restart()
                    page = await browser.new_page()

                try:
                    status, result = await process_one_barcode(
                        row["barcode"], row["scan_count"], http_client, page,
                        rate_limiter, config, logger, circuit_breaker, domain_limiter,
                    )
                    checkpoint.save(row["barcode"], status, result)
                except Exception as e:
                    logger.exception(f"Unhandled error on {row['barcode']}: {e}")
                    checkpoint.save(row["barcode"], "not_found", {
                        "barcode": row["barcode"], "barcode_type": "UNKNOWN",
                        "gs1_country": None, "sources_attempted": [f"error: {e}"],
                        "scan_count": row["scan_count"],
                    })
                finally:
                    if page is not None:
                        try:
                            await page.close()
                        except Exception as e:
                            logger.info(f"page.close() failed (ignored): {e}")
        except Exception as e:
            # last-resort catch: even a semaphore/browser-level failure
            # must not propagate out of this coroutine
            logger.exception(f"Worker-level failure on {row['barcode']}: {e}")
        finally:
            async with completed_lock:
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

    start = time.time()
    results = await asyncio.gather(*(worker(r) for r in pending), return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            logger.exception(f"Task raised despite guards: {r}")

    await http_client.aclose()
    await browser.stop()

    found = checkpoint.all_by_status("found")
    invalid = checkpoint.all_by_status("invalid")
    not_found = checkpoint.all_by_status("not_found")

    write_all(config["paths"], found, invalid, not_found)
    summary = {
        "total_rows": len(rows),
        "found": len(found),
        "invalid": len(invalid),
        "not_found": len(not_found),
        "runtime_seconds": round(time.time() - start, 1),
    }
    write_summary(config["paths"]["summary_json"], summary)
    checkpoint.close()

    logger.info(f"Done. found={len(found)} invalid={len(invalid)} not_found={len(not_found)}")
    return summary


async def lookup_single_barcode(barcode: str, config: dict, headless: bool = True) -> dict:
    """
    One-off lookup — used for the 'test a single barcode' box and for
    re-checking a barcode that's already in found_products.csv. Does NOT
    touch the checkpoint DB, so it never interferes with a batch run.
    """
    logger = setup_logging(config["paths"]["log_file"])
    rate_limiter = DomainRateLimiter(
        config["rate_limit"]["default_seconds_between_requests"],
        config["rate_limit"]["per_domain_overrides"],
    )
    circuit_breaker = DomainCircuitBreaker(
        failure_threshold=config.get("circuit_breaker", {}).get("failure_threshold", 4),
        enabled=False,  # a single lookup shouldn't trip/skip anything
    )
    domain_limiter = DomainConcurrencyLimiter(
        max_per_domain=config.get("max_concurrent_per_domain", 2),
    )

    browser = Browser(headless=headless)
    await browser.start()
    http_client = httpx.AsyncClient(follow_redirects=True)
    page = await browser.new_page()

    try:
        status, result = await process_one_barcode(
            barcode, None, http_client, page, rate_limiter, config, logger,
            circuit_breaker, domain_limiter,
        )
    finally:
        await page.close()
        await http_client.aclose()
        await browser.stop()

    return {"status": status, "result": result}