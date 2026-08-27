import argparse
import asyncio
import json

import yaml
from tqdm import tqdm

from src.runner import run_pipeline, lookup_single_barcode


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Halal scanner barcode enrichment pipeline")
    parser.add_argument("--input", help="Path to input CSV (batch mode)")
    parser.add_argument("--barcode", help="Look up a single barcode instead of running a batch")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--sample", type=int, default=None, help="Only process first N rows")
    parser.add_argument("--concurrency", type=int, default=None, help="Override config concurrency")
    parser.add_argument("--fresh", action="store_true", help="Ignore existing checkpoint, start clean")
    parser.add_argument("--headed", action="store_true", help="Run browser visibly (debugging)")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.concurrency:
        config["concurrency"] = args.concurrency

    if args.barcode:
        outcome = asyncio.run(lookup_single_barcode(args.barcode, config, headless=not args.headed))
        print(json.dumps(outcome, indent=2, ensure_ascii=False))
        return

    if not args.input:
        parser.error("--input is required unless using --barcode")

    progress_bar = tqdm(total=None, desc="Processing")

    def on_progress(done, total):
        if progress_bar.total != total:
            progress_bar.total = total
            progress_bar.refresh()
        progress_bar.n = done
        progress_bar.refresh()

    summary = asyncio.run(run_pipeline(
        args.input, config,
        sample=args.sample, fresh=args.fresh, headless=not args.headed,
        progress_callback=on_progress,
    ))
    progress_bar.close()

    print(f"\nfound={summary['found']} invalid={summary['invalid']} "
          f"not_found={summary['not_found']} runtime={summary['runtime_seconds']}s")
    print(f"Outputs written to: {config['paths']['found_csv'].rsplit('/', 1)[0]}/")


if __name__ == "__main__":
    main()
