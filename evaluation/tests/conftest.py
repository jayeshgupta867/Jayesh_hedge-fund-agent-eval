import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.db import build_db, load_csv_dir  # noqa: E402

POLICY = ROOT / "policy" / "limit_policy.json"
LAST_CLOSE = datetime(2026, 10, 28, 22, 0)
FRESH = datetime(2026, 10, 29, 8, 0)
STALE = datetime(2026, 10, 28, 15, 0)
SAMPLE = load_csv_dir(ROOT / "data" / "sample")


def idea(idea_id, ticker, sector="Healthcare", er=0.10, horizon=12, conviction=3,
         status="Pending", direction="LONG", thesis="Earnings revision upside"):
    return {"idea_id": idea_id, "ticker": ticker, "direction": direction, "sector": sector,
            "thesis": thesis, "expected_return": er, "horizon_months": horizon,
            "conviction": conviction, "status": status, "date_generated": "2026-10-20"}


@pytest.fixture
def make_db(tmp_path):
    def _make(ideas, positions=None, market=None):
        tables = {"fund": SAMPLE["fund"],
                  "idea_pipeline": ideas,
                  "positions_risk": SAMPLE["positions_risk"] if positions is None else positions}
        if market:
            tables["market_data"] = market
        return build_db(tmp_path / "test.db", tables)
    return _make


@pytest.fixture
def fresh_clock():
    return lambda: FRESH
