# Halal Scanner — Barcode Product Enrichment Pipeline

Finds and extracts product data (name, brand, ingredients, image, halal cert mentions)
for barcodes that Open Food Facts doesn't have — using free APIs, Playwright-driven
search, and rule-based scraping. No paid AI APIs.

## What it does

1. **Validate** — reads your CSV, classifies every barcode (EAN-13 / UPC-A / EAN-8 /
   QR-URL / GS1-DataMatrix / invalid), and checks GS1 checksums to catch scan errors.
2. **Free structured APIs** — checks Open Food Facts, Open Beauty Facts, Open Products
   Facts, and UPCitemdb (all free, no scraping) before touching the web.
3. **Search** — for anything still missing, runs a Google search (Playwright) and/or
   region-specific retailer site search, based on the barcode's GS1 country prefix.
4. **Link resolution** — if a search result is a homepage (not a product page), scans
   that page's links for product-shaped URLs, or falls back to that site's own search.
5. **Verify** — confirms the barcode/GTIN actually appears on the candidate page
   (in JSON-LD structured data or raw page text) before trusting anything on it.
6. **Translate** — detects page language, translates only the extracted fields (not
   the whole page) using offline Argos Translate. E-numbers are pulled out separately
   since they don't need translation.
7. **Extract** — pulls product name, brand, image, ingredients, country, and any halal
   cert text mention from JSON-LD / Open Graph tags first, falling back to common
   HTML patterns.
8. **Output** — three CSVs: found, invalid, not-found. Fully resumable (SQLite
   checkpoint) so a long run can be safely interrupted and restarted.

## Project structure

```
halal-barcode-enrichment/
├── main.py                  # CLI entry point
├── config.yaml              # rate limits, region routing, concurrency
├── requirements.txt
├── src/
│   ├── classify.py          # Stage 0: barcode type + checksum validation
│   ├── gs1_prefixes.py      # GS1 prefix → country lookup table
│   ├── pipeline.py          # orchestrates the whole per-barcode flow
│   ├── storage.py           # SQLite checkpoint / resume state
│   ├── writer.py            # writes the 3 output CSVs
│   ├── utils.py             # rate limiter, retry decorator, logging setup
│   ├── sources/
│   │   ├── open_facts.py    # Open Food/Beauty/Products Facts + UPCitemdb
│   │   └── region_routing.py# GS1 country → priority source list
│   └── scraper/
│       ├── browser.py       # Playwright: google search + page fetch
│       ├── link_finder.py   # homepage detection + product-link scoring
│       ├── verify.py        # barcode/GTIN-on-page verification scoring
│       ├── extract.py       # JSON-LD / OG-tag / fallback extraction
│       └── translate.py     # language detection + offline translation
├── data/                    # put your input CSV here
├── output/                  # found/invalid/not_found CSVs land here
└── logs/                    # run logs
```

## Setup (VS Code / local machine)

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 3. One-time translation setup: NONE NEEDED
# Translation uses deep-translator (free Google Translate web endpoint,
# no API key, no compiled dependencies, no model download).

# 4. Optional but recommended — start self-hosted SearxNG for search
#    (requires Docker Desktop). If you skip this, the pipeline
#    automatically falls back to the Playwright google.com search.
docker compose up -d
# check it's running: http://localhost:8080 should load in a browser

# 5. Put your CSV in data/, e.g. data/scan_histories.csv
```

## What changed for speed/accuracy

- **Tier 1 free APIs run in parallel**, not one after another — cuts that
  stage's latency to whichever single check is slowest (~4x faster).
- **Hybrid fetch**: every page is tried with a plain `httpx` GET first (no
  browser, much faster). Playwright only kicks in when the page's raw HTML
  has no JSON-LD/OG tags and looks like an empty JS shell.
- **Circuit breaker**: a domain that fails or blocks 4 times in a row during
  a run gets skipped for the rest of that run instead of wasting time on a
  source that's clearly dead right now. Resets on the next run.
- **SearxNG** (self-hosted, free, no key) replaces driving google.com through
  a browser for search discovery — it's a plain JSON API call (fast) and
  returns results across multiple engines regardless of the target page's
  language, since it doesn't localize/redirect the way a browser hitting
  google.com directly can.

## Single barcode lookup / re-check

Available in both the Streamlit sidebar and the CLI — useful for testing
one barcode without running a full batch, or spot-checking a result that's
already in `found_products.csv`.

```cmd
:: CLI
python main.py --barcode 8997021871295
```

In Streamlit, the sidebar has:
- **Single barcode lookup** — type any barcode, get an instant result
- **Re-check an existing result** — pick a barcode already in
  `found_products.csv` from a dropdown, re-run it fresh, and compare the
  old stored result against the new one side by side

## Running it

### Option A — Streamlit interface (recommended for day-to-day use)

```cmd
streamlit run streamlit_app.py
```

This opens a browser tab where you can:
- Upload your CSV directly (no need to manually copy it into `data/`)
- Toggle "test on a sample first" and set the sample size
- Adjust concurrency with a slider
- Watch a live progress bar while it runs
- Download `found_products.csv`, `not_found_products.csv`, and
  `invalid_barcodes.csv` directly from the page when it finishes
- Preview each result set in a table before downloading

Resumability still works the same way underneath — if you re-upload the same
file and run again, already-processed barcodes are skipped automatically
unless you tick "start fresh."

### Option B — Command line

```cmd
# Always test on a small sample first
python main.py --input data\scan_histories.csv --sample 50

# Full run (resumable — safe to Ctrl+C and re-run the same command)
python main.py --input data\scan_histories.csv

# Resume is automatic (checkpoint.db), but you can force a clean restart:
python main.py --input data\scan_histories.csv --fresh

# Tune concurrency / rate limits via config.yaml, or override:
python main.py --input data\scan_histories.csv --concurrency 8
```

## Output

- `output/found_products.csv` — barcode, type, gs1_country, product_name, brand,
  ingredients, image_url, country_of_origin, halal_cert_mentions, source_url,
  source_name, verification_score, scan_count
- `output/invalid_barcodes.csv` — original_value, detected_type, reason, scan_count
- `output/not_found_products.csv` — barcode, type, gs1_country, sources_attempted,
  scan_count — this is your manual-review queue, same shape as today's workflow
- `output/run_summary.json` — counts per bucket, per-source hit rate, runtime

## Things you'll need to tune after the first real run

- `config.yaml → region_routing`: site-search URL patterns are pre-filled for the
  major retailers we identified from your data (Lazada, Shopee, Tokopedia, JD, etc.)
  but you WILL find sites that need their pattern added — that's expected, add them
  as you go.
- Rate limits per domain — start conservative (already set low in config.yaml),
  loosen only if you're not seeing blocks.
- Known bot-walled domains (eBay, Amazon marketplace pages) are deprioritized by
  default in `region_routing.py` — extend that list as you discover more.

## Ethical / ToS note

This tool queries public retailer product pages for internal product-database
enrichment, not redistribution. It rate-limits per domain and caches results to
avoid hammering any single site. Review the target sites' terms of service for
your jurisdiction before running at large scale, and raise concurrency gradually.
"# Halal-Scanner-Product-Updater" 
