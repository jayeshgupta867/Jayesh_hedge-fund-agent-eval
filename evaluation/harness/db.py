"""U1 — read-only data access and snapshot pull.

The workflow never writes to the database. Two layers enforce that:
1. the SQLite connection is opened in read-only mode, and
2. every query goes through `ReadOnlyDB.query`, which refuses anything but SELECT
   and raises `WriteAttempt` (the absolute tripwire from the design).
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

UNDECIDED_STATUSES = {"New", "Pending"}


class WriteAttempt(Exception):
    """Raised when anything tries to modify the database. Stops the whole run."""


class ReadOnlyDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row
        self.queries = 0

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        if not sql.lstrip().upper().startswith("SELECT"):
            raise WriteAttempt(f"Blocked non-SELECT statement: {sql.split()[0]}")
        self.queries += 1
        try:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError as exc:  # e.g. readonly database
            if "readonly" in str(exc).lower():
                raise WriteAttempt(str(exc)) from exc
            raise

    def has_table(self, name: str) -> bool:
        rows = self.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return bool(rows)

    def close(self):
        self._conn.close()


def build_db(db_path: str | Path, tables: dict[str, list[dict]]) -> Path:
    """Create a test/demo database from rows. Used only to build fixtures."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    for name, rows in tables.items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        conn.execute(f"CREATE TABLE {name} ({', '.join(cols)})")
        conn.executemany(
            f"INSERT INTO {name} VALUES ({', '.join('?' for _ in cols)})",
            [tuple(_coerce(r[c]) for c in cols) for r in rows],
        )
    conn.commit()
    conn.close()
    return db_path


def load_csv_dir(folder: str | Path) -> dict[str, list[dict]]:
    tables = {}
    for f in sorted(Path(folder).glob("*.csv")):
        with open(f, newline="") as fh:
            tables[f.stem] = list(csv.DictReader(fh))
    return tables


def _coerce(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    for cast in (int, float):
        try:
            return cast(v)
        except (TypeError, ValueError):
            pass
    return v


@dataclass
class Snapshot:
    snapshot_id: str
    pulled_at: datetime
    nav: float
    ideas: list[dict]
    positions: list[dict]
    market: dict[str, dict] = field(default_factory=dict)

    def idea(self, idea_id: str) -> dict:
        return next(i for i in self.ideas if i["idea_id"] == idea_id)


def pull_snapshot(db: ReadOnlyDB, pulled_at: datetime) -> Snapshot:
    """U1: pull open ideas, the book and (if available) market data in one snapshot."""
    nav = db.query("SELECT nav FROM fund")[0]["nav"]
    ideas = db.query("SELECT * FROM idea_pipeline ORDER BY idea_id")
    positions = db.query("SELECT * FROM positions_risk ORDER BY ticker")
    market = {}
    if db.has_table("market_data"):
        market = {r["ticker"]: r for r in db.query("SELECT * FROM market_data")}
    payload = json.dumps([nav, ideas, positions, market], sort_keys=True, default=str)
    digest = hashlib.sha256((payload + pulled_at.isoformat()).encode()).hexdigest()[:12]
    return Snapshot(f"SNAP-{digest}", pulled_at, nav, ideas, positions, market)
