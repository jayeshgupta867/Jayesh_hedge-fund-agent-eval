"""One trading day.

    data guard → mark → exits → PM approvals → screen → harness → decisions → hedge → NAV

The harness (evaluation/harness) is used unchanged: it ranks, checks every memo, sizes and
checks limits. v4 adds, after the harness and before anything is booked:
  data quarantine · liquidity cap · correlation with the book · short crowding ·
  the analyst's challenge · PM sign-off for anything flagged · a SPY hedge book.
Every check can only shrink, stop or escalate a trade. None can create or enlarge one.
"""
from __future__ import annotations

import re
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from harness.limits import check_limits
from harness.run import run_workflow

from . import approvals as appr
from . import dataguard, risk
from .data import MarketContext, Prices
from .ledger import Ledger
from .policy import load_limit_policy
from .screen import features, screen

IDEA_COLS = ["idea_id", "ticker", "direction", "sector", "thesis", "expected_return",
             "horizon_months", "conviction", "status", "date_generated", "momentum_12_1",
             "pct_above_ma200", "vol_63d", "mom_percentile", "price"]
POS_COLS = ["ticker", "sector", "direction", "market_value", "pct_nav", "var_95", "settlement_status"]
NO_APPROVALS = {"items": [], "trusted": True, "warning": None}


def run_day(ledger: Ledger, prices: Prices, date: pd.Timestamp, universe: dict[str, str],
            policy_path: Path, rules: dict, overrides: dict, analyst, mode: str,
            ctx: MarketContext | None = None, approvals: dict | None = None) -> dict | None:
    d = f"{date:%Y-%m-%d}"
    if ledger.last_date and d <= ledger.last_date:
        return None  # already processed: re-running is a no-op
    ctx = ctx or MarketContext()
    approvals = approvals or NO_APPROVALS
    policy = load_limit_policy(policy_path)
    close = prices.close.loc[date]
    cost_bps = rules["transaction_cost_bps"]
    report = {"date": d, "mode": mode, "data_source": prices.source, "analyst": analyst.name,
              "policy_version": policy.get("version"), "rules_version": rules.get("version"),
              "exits": [], "executed": [], "skipped": [], "escalated": [], "approvals": [],
              "warnings": [], "pm_alerts": [], "data_checks": [], "decisions": {}, "hedge": None}

    # 0 · data guard: quarantine any ticker whose latest bar looks wrong (SPY glitch stops the day)
    quarantined, notes = dataguard.quarantine(prices, date, list(universe) + [risk.HEDGE_TICKER],
                                              policy["data"], ctx.confirm_close)
    report["data_checks"] = notes + [{"check": f"quarantine {t}", "result": "FAIL", "note": why}
                                     for t, why in quarantined.items()]

    # 1 · mark to market (quarantined names keep their last trusted mark)
    if ledger.last_date:
        stale = ledger.mark(prices.adj, prices.close, date, skip=set(quarantined))
        for t in stale:
            report["warnings"].append(f"{t}: not marked today (no trusted price), last mark kept")
    else:
        ledger.inception = d
    nav_open = ledger.nav_value
    report["nav_before_trades"] = round(nav_open, 2)

    # 2 · exits: long and short books have separate stops; the hedge has its own rule (step 7)
    feats = features(prices, date, list(universe))
    trading_days = [x for x in prices.dates if x <= date]
    for p in list(ledger.positions):
        if risk.book_of(p) == "HEDGE":
            continue
        t, reason = p["ticker"], None
        move = p["market_value"] / p["cost_basis"] - 1 if p["cost_basis"] else 0.0
        held_days = sum(1 for x in trading_days if x > pd.Timestamp(p["entry_date"]))
        pct = feats["mom_pct"].get(t)
        if t in overrides.get("close_tickers", []):
            reason = "PM override: close"
        elif p["direction"] == "LONG" and move <= -rules["stop_loss_pct"] / 100:
            reason = f"stop loss ({move:+.1%} price move)"
        elif p["direction"] == "SHORT" and move >= rules["stop_loss_short_pct"] / 100:
            reason = f"short stop / squeeze guard ({move:+.1%} price move against the short)"
        elif held_days >= rules["max_holding_days"]:
            reason = f"max holding period ({held_days} days)"
        elif pct is not None and ((p["direction"] == "LONG" and pct < rules["signal_exit_percentile"]) or
                                  (p["direction"] == "SHORT" and pct > 1 - rules["signal_exit_percentile"])):
            reason = f"signal faded (momentum percentile {pct:.0%})"
        if reason:
            px = close.get(t)
            if t in quarantined:
                report["pm_alerts"].append(f"{t}: exit wanted ({reason}) but today's price is quarantined "
                                           f"({quarantined[t]}); exit postponed, PM to review")
                continue
            if px is None or px != px:
                report["warnings"].append(f"{t}: no price today, exit postponed")
                continue
            report["exits"].append(ledger.close(d, t, float(px), cost_bps, reason))

    veto = set(overrides.get("veto_tickers", []))
    trades_today = 0

    # 3 · PM sign-offs for trades queued on an earlier day (live only)
    if ledger.pending:
        trades_today = _resolve_pending(ledger, prices, date, universe, policy, rules, veto, quarantined,
                                        approvals, report, feats, trades_today)

    # 4 · screen (never re-proposes a held, vetoed, quarantined or just-exited name)
    exited_today = {e["ticker"] for e in report["exits"]}
    ideas = screen(prices, date, universe, exclude=ledger.held() | veto | exited_today | set(quarantined),
                   allow_shorts=rules.get("allow_shorts", True))
    report["screen"] = {"ideas": len(ideas), "vetoed": sorted(veto & set(universe)),
                        "quarantined": sorted(set(quarantined) & set(universe))}

    # 5 · harness: rank → S1 drafts → checks → sizing → limits
    new_pending = []
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

        # 6 · decisions, in shortlist order; every check re-run against the book as it stands
        by_id = {i["idea_id"]: i for i in ideas}
        for c in res.shortlist:
            iid, t = c["idea_id"], c["ticker"]
            memo = res.memos.get(iid, {})
            dec = {"checks": []}
            report["decisions"][iid] = dec
            why = _rule_failure(memo, res.ideas.get(iid), rules, trades_today)
            if why:
                report["skipped"].append({"idea_id": iid, "ticker": t, "reason": why})
                continue
            idea = by_id[iid]
            outcome = evaluate(idea, memo["9_size_pct_nav"], ledger, prices, date, policy, rules, feats,
                               ctx, analyst, dec)
            _update_memo_flags(memo, dec)
            if outcome["action"] == "reject":
                report["skipped"].append({"idea_id": iid, "ticker": t, "reason": outcome["why"]})
                continue
            px = float(close[t])
            if outcome["action"] == "escalate":
                item = {"idea_id": iid, "ticker": t, "direction": idea["direction"], "sector": idea["sector"],
                        "pct_nav": round(outcome["pct_nav"], 4), "price": round(px, 4), "date_queued": d,
                        "reasons": outcome["flags"], "thesis": memo.get("2_thesis_summary", ""),
                        "idea": {k: idea[k] for k in ("idea_id", "ticker", "direction", "sector")}}
                item["token"] = appr.token(item)
                if mode == "live":
                    new_pending.append(item)
                    report["escalated"].append({k: item[k] for k in ("idea_id", "ticker", "direction", "pct_nav",
                                                                    "price", "token", "reasons")})
                else:
                    report["skipped"].append({"idea_id": iid, "ticker": t,
                                              "reason": "needs PM sign-off (not traded outside live mode): "
                                                        + "; ".join(outcome["flags"])})
                continue
            notional = outcome["pct_nav"] / 100 * ledger.nav_value
            cost = cost_bps + risk.impact_bps(notional, idea.get("adv_usd"), idea.get("vol_63d"), policy["liquidity"])
            if c["direction"] == "LONG" and notional * (1 + cost / 1e4) > ledger.cash:
                report["skipped"].append({"idea_id": iid, "ticker": t, "reason": "not enough cash"})
                continue
            report["executed"].append(ledger.open(d, idea, outcome["pct_nav"], px, cost,
                                                  "standing rules: memo and book checks passed"))
            trades_today += 1
    ledger.pending = new_pending
    report["analyst_log"] = getattr(analyst, "log", [])
    report["analyst_used"] = getattr(analyst, "used", analyst.name)

    # 7 · hedge book: bring beta-adjusted net exposure back to the target
    report["hedge"] = _rebalance_hedge(ledger, prices, date, rules, quarantined, d, cost_bps)

    # 8 · close the day
    spy = float(close.get("SPY"))
    first_spy = ledger.nav[0]["spy_close"] if ledger.nav else spy
    gross, net = ledger.exposures()
    nav = ledger.nav_value
    hedge_mv = sum(p["market_value"] for p in ledger.positions if risk.book_of(p) == "HEDGE")
    beta_net = (report["hedge"] or {}).get("beta_net_after_pct")
    ledger.nav.append({
        "date": d, "nav": round(nav, 2), "cash": round(ledger.cash, 2), "gross_pct": round(gross, 2),
        "net_pct": round(net, 2), "n_positions": len(ledger.positions),
        "daily_pnl": round(nav - (ledger.nav[-1]["nav"] if ledger.nav else ledger.capital), 2),
        "spy_close": round(spy, 2), "spy_index": round(spy / first_spy * 100, 4),
        "fund_index": round(nav / ledger.capital * 100, 4),
        "beta_net_pct": beta_net, "hedge_pct": round(hedge_mv / nav * 100, 2)})
    report["capacity_usd"] = risk.capacity_usd(ledger.positions, feats["adv_usd"].to_dict(), nav, policy["liquidity"])
    report["nav_after"] = round(nav, 2)
    return report


def evaluate(idea: dict, size_pct: float | None, ledger: Ledger, prices: Prices, date: pd.Timestamp,
             policy: dict, rules: dict, feats: pd.DataFrame, ctx: MarketContext, analyst, dec: dict) -> dict:
    """Book-level checks for one trade-ready idea. Returns {action, pct_nav, flags, why}.

    action: trade · escalate (PM sign-off) · reject. Checks only ever lower the size.
    """
    checks, flags = dec["checks"], []
    t, direction = idea["ticker"], idea["direction"]
    nav = ledger.nav_value

    final, lines = check_limits(idea, size_pct, ledger.as_positions_risk(), policy)
    checks.append({"check": "limits (harness)", "result": "PASS" if final else "FAIL",
                   "note": f"{final:.2f}% NAV after headroom" if final else "limit reached after earlier fills today"})
    if not final or final <= 0:
        return {"action": "reject", "why": "limit reached after earlier fills today", "pct_nav": 0, "flags": flags}

    cap = risk.liquidity_cap_pct(idea.get("adv_usd"), nav, policy["liquidity"])
    if cap is None:
        checks.append({"check": "liquidity", "result": "NOT ASSESSED", "note": "no volume data: size withheld"})
        return {"action": "reject", "why": "liquidity unknown (no ADV): size withheld", "pct_nav": 0, "flags": flags}
    lp = policy["liquidity"]
    checks.append({"check": "liquidity", "result": "PASS",
                   "note": f"max trade ${cap / 100 * nav / 1e6:,.1f}m = {lp['max_trade_pct_adv']}% of ADV "
                           f"${idea['adv_usd'] / 1e9:,.2f}bn" + (": binding, size cut" if cap < final else
                                                                 f"; this trade ${final / 100 * nav / 1e3:,.0f}k")})
    final = min(final, cap)

    corr = risk.correlation_check(prices, date, t, direction, ledger.positions, policy["correlation"])
    checks.append({"check": "correlation with book", "result": corr["result"], "note": corr["note"],
                   "rho_book": corr["rho_book"], "max_pair": corr["max_pair"], "pair_ticker": corr["pair_ticker"]})
    dec["correlation"] = corr
    if corr["action"] == "reject":
        return {"action": "reject", "why": corr["note"], "pct_nav": 0, "flags": flags}
    if corr["action"] == "halve":
        final /= 2
    elif corr["action"] == "escalate":
        flags.append(f"correlation not assessed: {corr['note']}")

    if direction == "SHORT":
        crowd = risk.crowding_check(ctx.short_interest(t) if ctx.point_in_time else None,
                                    rules["short_book"], ctx.point_in_time)
        checks.append({"check": "short crowding", **crowd})
        if crowd["action"] == "reject":
            return {"action": "reject", "why": crowd["note"], "pct_nav": 0, "flags": flags}
        if crowd["action"] == "escalate":
            flags.append(crowd["note"])

    facts = risk.signal_facts(prices, date, t)
    challenges = analyst.challenge(idea, facts)
    dec["facts"], dec["challenges"] = facts, challenges
    for ch in challenges:
        checks.append({"check": "analyst challenge", "result": "ESCALATE" if ch["action"] == "escalate" else "NOTE",
                       "note": ch["issue"]})
        if ch["action"] == "escalate":
            flags.append(f"analyst: {ch['issue']}")

    if not any(ch["action"] == "escalate" for ch in challenges):
        checks.append({"check": "analyst challenge", "result": "PASS", "note": "no escalation"})
    dec["final_pct_nav"] = round(final, 4)
    return {"action": "escalate" if flags else "trade", "pct_nav": final, "flags": flags, "why": ""}


def _resolve_pending(ledger, prices, date, universe, policy, rules, veto, quarantined, approvals,
                     report, feats, trades_today) -> int:
    d = f"{date:%Y-%m-%d}"
    dates = [f"{x:%Y-%m-%d}" for x in prices.dates if x <= date]
    cfg = rules["approvals"]
    if approvals.get("warning"):
        report["pm_alerts"].append(approvals["warning"])
    close = prices.close.loc[date]
    for item in ledger.pending:
        t = item["ticker"]
        rec = {"idea_id": item["idea_id"], "ticker": t, "token": item["token"]}
        report["approvals"].append(rec)
        a = appr.find_approval(item, approvals["items"])
        if appr.is_expired(item, d, dates, cfg["valid_trading_days"]):
            rec["result"] = "expired: approval window closed"
        elif a is None:
            rec["result"] = "no PM decision: dropped (the screen may propose it again)"
        elif not approvals.get("trusted"):
            rec["result"] = "approval ignored: " + (approvals.get("warning") or "untrusted source")
        elif not appr.token_matches(item, a):
            rec["result"] = "approval rejected: token does not match the queued trade"
        elif str(a.get("decision", "")).lower() != "approve":
            rec["result"] = f"PM decision: {a.get('decision', 'none')}"
        elif t in veto:
            rec["result"] = "not booked: PM veto overrides the approval (most restrictive rule wins)"
        elif t in quarantined:
            rec["result"] = f"not booked: price quarantined ({quarantined[t]})"
        elif t in ledger.held():
            rec["result"] = "not booked: already held"
        elif trades_today >= rules["max_new_trades_per_day"]:
            rec["result"] = "not booked: daily trade limit reached"
        else:
            px = close.get(t)
            drift = abs(float(px) / item["price"] - 1) * 100 if px == px and px is not None else None
            if drift is None:
                rec["result"] = "not booked: no price today"
            elif drift > cfg["max_price_drift_pct"]:
                rec["result"] = f"approval void: price moved {drift:.1f}% since queued (> {cfg['max_price_drift_pct']}%)"
            else:
                idea = item["idea"] | {"adv_usd": float(feats["adv_usd"].get(t, float("nan")))}
                final, _ = check_limits(idea, item["pct_nav"], ledger.as_positions_risk(), policy)
                corr = risk.correlation_check(prices, date, t, item["direction"], ledger.positions,
                                              policy["correlation"])
                cap = risk.liquidity_cap_pct(idea["adv_usd"], ledger.nav_value, policy["liquidity"])
                if not final or final <= 0 or corr["action"] == "reject" or cap is None:
                    rec["result"] = "not booked: limits, liquidity or correlation fail at today's book"
                else:
                    size = min(final, cap, item["pct_nav"]) / (2 if corr["action"] == "halve" else 1)
                    tr = ledger.open(d, idea, size, float(px), rules["transaction_cost_bps"],
                                     f"PM approved (token {item['token']})")
                    report["executed"].append(tr)
                    rec["result"] = f"booked at {size:.2f}% NAV (approved ceiling {item['pct_nav']:.2f}%)"
                    trades_today += 1
    return trades_today


def _rebalance_hedge(ledger, prices, date, rules, quarantined, d, cost_bps) -> dict | None:
    cfg = rules["hedge"]
    if not cfg.get("enabled"):
        return None
    nav = ledger.nav_value
    book = [p for p in ledger.positions if risk.book_of(p) != "HEDGE"]
    beta = risk.betas(prices, date, [p["ticker"] for p in book], int(cfg["beta_window_days"]))
    tgt = risk.hedge_target(ledger.positions, beta, nav, cfg)
    current = sum(p["market_value"] for p in ledger.positions if risk.book_of(p) == "HEDGE")
    out = {"book_beta_pct": tgt["book_beta_pct"], "target_pct": round(tgt["target_mv"] / nav * 100, 2),
           "before_pct": round(current / nav * 100, 2), "traded": False, "beta_assumed_1": tgt["beta_assumed_1"]}
    if risk.HEDGE_TICKER in quarantined:
        out["note"] = "SPY price quarantined: hedge unchanged"
    elif abs(tgt["target_mv"] - current) / nav * 100 > cfg["rebalance_band_pct"] or (not book and current):
        px = float(prices.close.at[date, risk.HEDGE_TICKER])
        target = 0.0 if not book else tgt["target_mv"]
        out["trades"] = ledger.set_hedge(d, risk.HEDGE_TICKER, risk.HEDGE_SECTOR, risk.HEDGE_ID, target, px,
                                         cost_bps, f"hedge: beta-adjusted net {tgt['book_beta_pct']:+.1f}% → "
                                                   f"{cfg['target_net_beta_pct']:+.0f}% target")
        out["traded"] = True
        current = target
    else:
        out["note"] = f"within the ±{cfg['rebalance_band_pct']}% band: no trade"
    out["after_pct"] = round(current / ledger.nav_value * 100, 2)
    out["beta_net_after_pct"] = round(tgt["book_beta_pct"] + out["after_pct"], 2)
    return out


def _update_memo_flags(memo: dict, dec: dict) -> None:
    """The harness flags correlation as NOT ASSESSED; the fund layer now assesses it."""
    corr = dec.get("correlation")
    if not corr or not memo.get("top_flags"):
        return
    memo["top_flags"] = [f"Correlation with book: {corr['result']} – {corr['note']}" if f.startswith("Aggregate/correlation")
                         else f for f in memo["top_flags"]]
    memo["book_checks"] = dec["checks"]


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
                     [(i["ticker"], i["vol_63d"], i.get("adv_usd")) for i in ideas])
    conn.commit()
    conn.close()
    return path
