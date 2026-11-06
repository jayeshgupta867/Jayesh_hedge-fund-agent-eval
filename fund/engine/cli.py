"""Command line entry points (used by GitHub Actions and locally).

    python -m fund.engine.cli live              # process the latest closed trading day
    python -m fund.engine.cli replay --days 60  # rebuild the replay track record

The engine reads fund/policy and writes only under fund/state. A run that cannot trust its
inputs (prices, policy files) records why and trades nothing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import approvals as appr
from . import dataguard
from .analyst import make_analyst
from .data import DataError, MarketContext, Prices, live_context, load_prices
from .day import run_day
from .ledger import Ledger
from .policy import PolicyError, load_limit_policy, load_overrides, load_rules
from .universe import BENCHMARK, UNIVERSE

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policy"
STATE = ROOT / "state"
PROTECTED = [POLICY, ROOT / "engine", ROOT / "tests", ROOT.parent / "evaluation", ROOT.parent / ".github"]


def guard_state_root(state_root: Path) -> Path:
    """The engine may write results only under its state folder, never next to its own
    policy, code or tests (an automated process must not be able to edit its own rules)."""
    p = Path(state_root).resolve()
    for forbidden in PROTECTED:
        f = forbidden.resolve()
        if p == f or f in p.parents:
            raise PermissionError(f"refusing to write fund state into {forbidden.relative_to(ROOT.parent)}")
    return p


def run(mode: str, days: int = 60, prices: Prices | None = None, state_root: Path = STATE,
        universe: dict | None = None, ctx: MarketContext | None = None, now: datetime | None = None,
        approvals: dict | None = None, policy_dir: Path = POLICY) -> list[dict]:
    state_root = guard_state_root(state_root)
    universe = universe or UNIVERSE
    rules = load_rules(policy_dir / "standing_rules.json")
    overrides = load_overrides(policy_dir / "pm_overrides.json")
    limit_policy = load_limit_policy(policy_dir / "limit_policy.json")
    if prices is None:
        prices = load_prices(list(universe) + [BENCHMARK])
    live_notes = []
    if mode == "live":
        prices, live_notes = dataguard.prepare_live(prices, now or datetime.now(timezone.utc), limit_policy["data"])
        ctx = ctx or live_context()
        if approvals is None:
            approvals = appr.load_pm_approvals(policy_dir / "pm_approvals.json")
    else:
        ctx = ctx or MarketContext(point_in_time=False)
        approvals = {"items": [], "trusted": True, "warning": None}
    out = state_root / mode
    if mode == "replay" and out.exists():
        shutil.rmtree(out)  # a replay is always rebuilt from scratch, so it is reproducible
    ledger = Ledger.load(out, capital=float(rules["starting_capital"]))
    dates = prices.dates[-days:] if mode == "replay" else prices.dates[-1:]
    reports = []
    for date in dates:
        rep = run_day(ledger, prices, date, universe, policy_dir / "limit_policy.json", rules,
                      overrides if mode == "live" else {}, make_analyst(mode), mode, ctx, approvals)
        if rep is None:
            print(f"[{mode}] {date:%Y-%m-%d} already processed, nothing to do")
            continue
        rep["data_checks"] = live_notes + rep["data_checks"]
        reports.append(rep)
        (out / "days").mkdir(parents=True, exist_ok=True)
        (out / "days" / f"{rep['date']}.json").write_text(json.dumps(rep, indent=1, default=str))
        print(f"[{mode}] {rep['date']} NAV {rep['nav_after']:,.0f} · {len(rep['executed'])} opened · "
              f"{len(rep['exits'])} closed · {len(rep['escalated'])} to PM · analyst {rep['analyst_used']}")
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
        pend = sum(len(r["escalated"]) for r in reps)
        status |= {"ok": True, "message": f"{len(reps)} day(s) processed"
                                          + (f" · {pend} trade(s) awaiting PM" if pend else "")}
        code = 0
    except DataError as exc:
        status |= {"ok": False, "message": f"no trading: price data problem ({exc})"}
        code = 1
    except PolicyError as exc:
        status |= {"ok": False, "message": f"no trading: policy file problem ({exc})"}
        code = 1
    except PermissionError as exc:
        status |= {"ok": False, "message": f"no trading: write guard ({exc})"}
        code = 1
    STATE.mkdir(exist_ok=True)
    (STATE / f"status_{a.mode}.json").write_text(json.dumps(status, indent=2))
    print(status["message"])
    return code


if __name__ == "__main__":
    sys.exit(main())
