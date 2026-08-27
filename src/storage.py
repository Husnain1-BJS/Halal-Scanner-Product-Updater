"""
Resumability. A long run over thousands of barcodes WILL get interrupted —
network blips, a bad site hanging, you closing the laptop. This lets you
Ctrl+C and re-run the same command without redoing finished work.
"""

import json
import sqlite3
from pathlib import Path


class Checkpoint:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                barcode TEXT PRIMARY KEY,
                status TEXT NOT NULL,      -- found / invalid / not_found
                payload TEXT,              -- JSON blob of the result row
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self.conn.commit()

    def already_done(self, barcode: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM results WHERE barcode = ?", (barcode,)
        ).fetchone()
        return row is not None

    def save(self, barcode: str, status: str, payload: dict):
        self.conn.execute(
            "INSERT OR REPLACE INTO results (barcode, status, payload) VALUES (?, ?, ?)",
            (barcode, status, json.dumps(payload)),
        )
        self.conn.commit()

    def all_by_status(self, status: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM results WHERE status = ?", (status,)
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def counts(self) -> dict:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) FROM results GROUP BY status"
        ).fetchall()
        return dict(rows)

    def close(self):
        self.conn.close()
