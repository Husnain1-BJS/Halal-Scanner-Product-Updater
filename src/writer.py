import csv
import json
from pathlib import Path

FOUND_COLUMNS = [
    "barcode", "barcode_type", "gs1_country", "product_name", "brand",
    "ingredients", "e_numbers_found", "image_url", "country_of_origin",
    "halal_cert_mentions", "source_url", "source_name",
    "verification_score", "confidence", "scan_count",
]

INVALID_COLUMNS = ["original_value", "detected_type", "reason", "scan_count"]

NOT_FOUND_COLUMNS = [
    "barcode", "barcode_type", "gs1_country", "sources_attempted", "scan_count",
]


def _write_csv(path: str, columns: list[str], rows: list[dict]):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            flat = {}
            for col in columns:
                value = row.get(col)
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                flat[col] = value
            writer.writerow(flat)


def write_all(paths: dict, found: list[dict], invalid: list[dict], not_found: list[dict]):
    _write_csv(paths["found_csv"], FOUND_COLUMNS, found)
    _write_csv(paths["invalid_csv"], INVALID_COLUMNS, invalid)
    _write_csv(paths["not_found_csv"], NOT_FOUND_COLUMNS, not_found)


def write_summary(path: str, summary: dict):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)