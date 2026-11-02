"""Command line entry points (used by GitHub Actions and locally).

    python -m fund.engine.cli live            # process the latest trading day
    python -m fund.engine.cli replay --days 60  # rebuild the replay track record
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .analyst import make_analyst
from .data import DataError, Prices, load_prices
from .day import run_day
from .ledger import Ledger
from .universe import BENCHMARK, UNIVERSE

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policy"
STATE = ROOT / "state"


def run(mode: str, days: int = 60, prices: Prices | None = None, state_root: Path = STATE,
        universe: dict | None = None) -> list[dict]:
    universe = universe or UNIVERSE
    rules = json.loads((POLICY / "standing_rules.json").read_text())
    overrides = json.loads((POLICY / "pm_overrides.json").read_text())
    if prices is None:
        prices = load_prices(list(universe) + [BENCHMARK])
    out = state_root / mode
    if mode == "replay" and out.exists():
        shutil.rmtree(out)  # a replay is always rebuilt from scratch, so it is reproducible
    ledger = Ledger.load(out, capital=float(rules["starting_capital"]))
    dates = prices.dates[-days:] if mode == "replay" else prices.dates[-1:]
    reports = []
    for date in dates:
        rep = run_day(ledger, prices, date, universe, POLICY / "limit_policy.json", rules,
                      overrides if mode == "live" else {}, make_analyst(mode), mode)
        if rep is None:
            print(f"[{mode}] {date:%Y-%m-%d} already processed, nothing to do")
            continue
        reports.append(rep)
        (out / "days").mkdir(parents=True, exist_ok=True)
        (out / "days" / f"{rep['date']}.json").write_text(json.dumps(rep, indent=1, default=str))
        print(f"[{mode}] {rep['date']} NAV {rep['nav_after']:,.0f} · {len(rep['executed'])} opened · "
              f"{len(rep['exits'])} closed · analyst {rep['analyst']}")
    ledger.save()
    return reports


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["live", "replay"])
    ap.add_argument("--days", type=int, default=60)
    a = ap.parse_args(argv)
    status = {"mode": a.mode, "run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
    try:
        reps = run(a.mode, a.days)
        status |= {"ok": True, "message": f"{len(reps)} day(s) processed"}
        code = 0
    except DataError as exc:
        status |= {"ok": False, "message": f"no trading: price data problem ({exc})"}
        code = 1
    STATE.mkdir(exist_ok=True)
    (STATE / f"status_{a.mode}.json").write_text(json.dumps(status, indent=2))
    print(status["message"])
    return code


if __name__ == "__main__":
    sys.exit(main())
