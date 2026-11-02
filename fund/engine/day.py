"""One trading day: mark → exits → screen → harness → standing rules → paper fills → NAV.

The harness (evaluation/harness) is used unchanged. The PM is represented by standing
rules written in advance (fund/policy/standing_rules.json) and a veto file
(fund/policy/pm_overrides.json) that the PM can edit at any time.
"""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from harness.limits import check_limits
from harness.run import run_workflow

from .data import Prices
from .ledger import Ledger
from .screen import features, screen

IDEA_COLS = ["idea_id", "ticker", "direction", "sector", "thesis", "expected_return",
             "horizon_months", "conviction", "status", "date_generated", "momentum_12_1",
             "pct_above_ma200", "vol_63d", "mom_percentile", "price"]
POS_COLS = ["ticker", "sector", "direction", "market_value", "pct_nav", "var_95", "settlement_status"]


def run_day(ledger: Ledger, prices: Prices, date: pd.Timestamp, universe: dict[str, str],
            policy_path: Path, rules: dict, overrides: dict, analyst, mode: str) -> dict | None:
    d = f"{date:%Y-%m-%d}"
    if ledger.last_date and d <= ledger.last_date:
        return None  # already processed: re-running is a no-op
    policy = json.loads(Path(policy_path).read_text())
    close = prices.close.loc[date]
    report = {"date": d, "mode": mode, "data_source": prices.source, "analyst": analyst.name,
              "policy_version": policy.get("version"), "rules_version": rules.get("version"),
              "exits": [], "executed": [], "skipped": [], "warnings": []}

    # 1 · mark to market
    if ledger.last_date:
        prev = pd.Timestamp(ledger.last_date)
        ratio = (prices.adj.loc[date] / prices.adj.loc[prev]).to_dict()
        ledger.mark(ratio, close.to_dict())
    else:
        ledger.inception = d
    nav_open = ledger.nav_value
    report["nav_before_trades"] = round(nav_open, 2)

    # 2 · exits (standing rules + PM close list)
    feats = features(prices, date, list(universe))
    trading_days = [x for x in prices.dates if x <= date]
    for p in list(ledger.positions):
        t, reason = p["ticker"], None
        move = p["market_value"] / p["cost_basis"] - 1 if p["cost_basis"] else 0.0
        held_days = sum(1 for x in trading_days if x > pd.Timestamp(p["entry_date"]))
        pct = feats["mom_pct"].get(t)
        if t in overrides.get("close_tickers", []):
            reason = "PM override: close"
        elif (p["direction"] == "LONG" and move <= -rules["stop_loss_pct"] / 100) or \
             (p["direction"] == "SHORT" and move >= rules["stop_loss_pct"] / 100):
            reason = f"stop loss ({move:+.1%} price move)"
        elif held_days >= rules["max_holding_days"]:
            reason = f"max holding period ({held_days} days)"
        elif pct is not None and ((p["direction"] == "LONG" and pct < rules["signal_exit_percentile"]) or
                                  (p["direction"] == "SHORT" and pct > 1 - rules["signal_exit_percentile"])):
            reason = f"signal faded (momentum percentile {pct:.0%})"
        if reason:
            px = close.get(t)
            if px is None or px != px:
                report["warnings"].append(f"{t}: no price today, exit postponed")
                continue
            report["exits"].append(ledger.close(d, t, float(px), rules["transaction_cost_bps"], reason))

    # 3 · screen (never re-proposes a held or vetoed name)
    veto = set(overrides.get("veto_tickers", []))
    exited_today = {e["ticker"] for e in report["exits"]}  # no same-day round trips
    ideas = screen(prices, date, universe, exclude=ledger.held() | veto | exited_today,
                   allow_shorts=rules.get("allow_shorts", True))
    report["screen"] = {"ideas": len(ideas), "vetoed": sorted(veto & set(universe))}

    # 4 · harness: rank → S1 drafts → checks → sizing → limits
    if ideas:
        with tempfile.TemporaryDirectory() as tmp:
            db = _build_db(Path(tmp) / "fund.db", ledger, ideas, policy)
            close_dt = datetime(date.year, date.month, date.day, 21, 0)
            res = run_workflow(db, policy_path, analyst, close_dt, lambda: close_dt + timedelta(hours=1),
                               pm_gate1=lambda cands, exc: [c["idea_id"] for c in cands])
        report["harness"] = {
            "status": res.status, "stop_reason": res.stop_reason, "snapshot_id": res.snapshot_id,
            "shortlist": [{k: c[k] for k in ("rank", "idea_id", "ticker", "direction", "sector", "score",
                                             "conviction", "momentum_12_1")} | {"reason": res.reasons.get(c["idea_id"], "")}
                          for c in res.shortlist],
            "exceptions": [{"idea_id": e["idea_id"], "ticker": e["ticker"], "note": e["note"]} for e in res.exceptions],
            "ideas": res.ideas, "repairs": res.repairs, "receipts": res.receipts,
            "boundaries": res.boundaries, "memos": res.memos,
        }
        # 5 · standing rules decide, in shortlist order; limits re-checked after every fill
        by_id = {i["idea_id"]: i for i in ideas}
        for c in res.shortlist:
            iid = c["idea_id"]
            memo = res.memos.get(iid, {})
            why = _rule_failure(memo, res.ideas.get(iid), rules, len(report["executed"]))
            if not why:
                size = memo["9_size_pct_nav"]
                final, lines = check_limits(by_id[iid], size, ledger.as_positions_risk(), policy)
                px = float(close[c["ticker"]])
                notional = final / 100 * ledger.nav_value if final else 0
                if not final or final <= 0:
                    why = "limit reached after earlier fills today"
                elif c["direction"] == "LONG" and notional * (1 + rules["transaction_cost_bps"] / 1e4) > ledger.cash:
                    why = "not enough cash"
                else:
                    report["executed"].append(ledger.open(d, by_id[iid], final, px, rules["transaction_cost_bps"]))
                    continue
            report["skipped"].append({"idea_id": iid, "ticker": c["ticker"], "reason": why})
    report["analyst_log"] = getattr(analyst, "log", [])

    # 6 · close the day
    spy = float(close.get("SPY"))
    first_spy = ledger.nav[0]["spy_close"] if ledger.nav else spy
    gross, net = ledger.exposures()
    nav = ledger.nav_value
    ledger.nav.append({
        "date": d, "nav": round(nav, 2), "cash": round(ledger.cash, 2), "gross_pct": round(gross, 2),
        "net_pct": round(net, 2), "n_positions": len(ledger.positions),
        "daily_pnl": round(nav - (ledger.nav[-1]["nav"] if ledger.nav else ledger.capital), 2),
        "spy_close": round(spy, 2), "spy_index": round(spy / first_spy * 100, 4),
        "fund_index": round(nav / ledger.capital * 100, 4)})
    report["nav_after"] = round(nav, 2)
    return report


def _rule_failure(memo: dict, state: str | None, rules: dict, n_done: int) -> str | None:
    if state != "MEMO_READY":
        return f"no memo ({state})"
    if n_done >= rules["max_new_trades_per_day"]:
        return "daily trade limit reached"
    if any(f.startswith("LIMIT FAIL") for f in memo["top_flags"]):
        return "a limit failed in the harness"
    if memo["9_size_pct_nav"] is None:
        return "size withheld (missing data)"
    m = re.match(r"(\d+)", str(memo["7_conviction_proposed"]))
    if not m or int(m.group(1)) < rules["min_conviction"]:
        return f"conviction below {rules['min_conviction']}"
    return None


def _build_db(path: Path, ledger: Ledger, ideas: list[dict], policy: dict) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE fund (nav REAL)")
    conn.execute("INSERT INTO fund VALUES (?)", (ledger.nav_value,))
    conn.execute(f"CREATE TABLE positions_risk ({', '.join(POS_COLS)})")
    conn.executemany(f"INSERT INTO positions_risk VALUES ({', '.join('?' * len(POS_COLS))})",
                     [tuple(p[c] for c in POS_COLS) for p in ledger.as_positions_risk()])
    conn.execute(f"CREATE TABLE idea_pipeline ({', '.join(IDEA_COLS)})")
    conn.executemany(f"INSERT INTO idea_pipeline VALUES ({', '.join('?' * len(IDEA_COLS))})",
                     [tuple(i[c] for c in IDEA_COLS) for i in ideas])
    conn.execute("CREATE TABLE market_data (ticker, volatility, adv_usd)")
    conn.executemany("INSERT INTO market_data VALUES (?, ?, ?)",
                     [(i["ticker"], i["vol_63d"], _adv(i)) for i in ideas])
    conn.commit()
    conn.close()
    return path


def _adv(idea: dict) -> float | None:
    return idea.get("adv_usd")
