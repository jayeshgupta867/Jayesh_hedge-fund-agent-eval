"""Run one pass of the workflow: U1 → U2 → U3 → gate 1 → U5/U6 → U7 → U8 → U9.

Ends with memos awaiting the PM at gate 2 (field 11 blank) or a CLOSED/STOPPED run.
The harness owns every number; S1 (the agent) only drafts text.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .checks import TrayMismatch, check_memo, check_reasons, validate_tray
from .db import ReadOnlyDB, WriteAttempt, pull_snapshot
from .limits import check_limits
from .rank import RANKING_RULE, shortlist
from .sizing import size_position

MAX_REPAIRS = 2
MAX_REPULLS = 2
ALLOWED_S1_FILES = ("reasons.json", "memo_draft_", "conviction_")


@dataclass
class RunResult:
    status: str                                   # AWAITING_GATE2 / CLOSED / STOPPED
    stop_reason: str = ""
    snapshot_id: str = ""
    pulls: int = 0
    shortlist: list[dict] = field(default_factory=list)
    exceptions: list[dict] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    memos: dict[str, dict] = field(default_factory=dict)
    ideas: dict[str, str] = field(default_factory=dict)   # idea_id -> idea status
    receipts: list[dict] = field(default_factory=list)
    repairs: dict[str, int] = field(default_factory=dict)
    note: str = ""
    boundaries: dict = field(default_factory=dict)


def _receipt(res: RunResult, tray, frm, to, ok, reason=""):
    res.receipts.append({"tray": tray, "from": frm, "to": to,
                         "result": "PASS" if ok else "FAIL", "reason": reason})


def run_workflow(
    db_path: str | Path,
    policy_path: str | Path,
    agent,
    last_close: datetime,
    clock: Callable[[], datetime],
    pm_gate1: Callable[[list[dict], list[dict]], list[str]] | None = None,
    tray_hook: Callable[[dict, int], dict] | None = None,
) -> RunResult:
    res = RunResult(status="OPEN")

    # Stop conditions: no policy or no database means no memo.
    try:
        policy = json.loads(Path(policy_path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return _stop(res, f"limit policy missing or unreadable: {exc}")
    try:
        db = ReadOnlyDB(db_path)
    except Exception as exc:  # noqa: BLE001
        return _stop(res, f"database unreachable: {exc}")

    try:
        # U1 + freshness check, re-pull when stale or when trays disagree
        for attempt in range(MAX_REPULLS + 1):
            snap = pull_snapshot(db, clock())
            res.pulls += 1
            if snap.pulled_at < last_close:
                _receipt(res, "snapshot", "U1", "harness", False,
                         f"stale: pulled {snap.pulled_at:%Y-%m-%d %H:%M} before close")
                continue
            res.snapshot_id = snap.snapshot_id

            # U2
            top, exceptions = shortlist(snap, policy)
            cand_tray = {"snapshot_id": snap.snapshot_id, "rows": top}
            if tray_hook:
                cand_tray = tray_hook(cand_tray, attempt)
            try:
                validate_tray(cand_tray, res.snapshot_id, {r["idea_id"] for r in top})
            except TrayMismatch as exc:
                _receipt(res, "candidates.json", "U2", "S1", False, str(exc))
                continue
            _receipt(res, "candidates.json", "U2", "S1", True)
            break
        else:
            return _stop(res, "snapshot stale or inconsistent after re-pulls")

        res.shortlist, res.exceptions = top, exceptions
        for e in exceptions:
            res.ideas[e["idea_id"]] = "EXCEPTION"

        if not top:
            res.status = "CLOSED"
            res.note = "0 candidates – exceptions reviewed by PM"
            return _finish(res, agent, db, policy)

        # U3: one-line reasons, checked before the harness assembles the shortlist
        reasons = agent.reasons(cand_tray)
        fails = check_reasons(reasons, {r["idea_id"] for r in top})
        _receipt(res, "reasons.json", "S1", "harness", not fails, "; ".join(map(str, fails)))
        if fails:
            return _stop(res, "shortlist reasons failed validation")
        res.reasons = {r["idea_id"]: r["reason"] for r in reasons}
        for c in top:
            res.ideas[c["idea_id"]] = "CANDIDATE"

        # U4: gate 1 (PM). Default: PM selects every candidate.
        selected_ids = (pm_gate1 or (lambda c, e: [x["idea_id"] for x in c]))(top, exceptions)
        for c in top:
            res.ideas[c["idea_id"]] = "SELECTED" if c["idea_id"] in selected_ids else "REJECTED"
        selected = [c for c in top if c["idea_id"] in selected_ids]
        sel_tray = {"snapshot_id": snap.snapshot_id, "rows": selected}
        validate_tray(sel_tray, res.snapshot_id, set(selected_ids))
        _receipt(res, "selected.json", "PM", "S1", True)

        # U5/U6 + checks, with targeted repair; then U7/U8/U9
        for row in selected:
            iid = row["idea_id"]
            feedback = None
            for attempt in range(MAX_REPAIRS + 1):
                memo = agent.draft_memo(row, snap.snapshot_id, feedback)
                conv = None if memo.get("status") == "INSUFFICIENT_EVIDENCE" else agent.conviction(memo)
                fails = check_memo(memo, conv, row, snap.snapshot_id)
                _receipt(res, f"memo_draft_{iid}", "S1", "harness", not fails,
                         "; ".join(map(str, fails)))
                if not fails:
                    break
                if attempt < MAX_REPAIRS:
                    res.repairs[iid] = attempt + 1
                feedback = [str(f) for f in fails]
            else:
                res.ideas[iid] = "STOPPED"
                res.memos[iid] = {"idea_id": iid, "status": "STOPPED",
                                  "reason": "failed checks after 2 repairs", "failures": feedback}
                continue

            if memo["status"] == "INSUFFICIENT_EVIDENCE":
                res.ideas[iid] = "INSUFFICIENT_EVIDENCE"   # never retried, never sized
                res.memos[iid] = {"idea_id": iid, "status": "INSUFFICIENT_EVIDENCE",
                                  "missing": memo["missing"]}
                continue

            size, size_note = size_position(conv["conviction_proposed"],
                                            snap.market.get(row["ticker"]), snap.nav, policy)
            final, report = check_limits(row, size, snap.positions, policy)
            res.memos[iid] = _assemble(row, memo, snap, final, size_note, report, policy)
            res.ideas[iid] = "MEMO_READY"

        res.status = "AWAITING_GATE2" if any(
            v == "MEMO_READY" for v in res.ideas.values()) else "CLOSED"
        return _finish(res, agent, db, policy)

    except WriteAttempt as exc:
        return _stop(res, f"TRIPWIRE – database write attempted: {exc}")
    finally:
        db.close()


def _assemble(row, memo, snap, final, size_note, report, policy) -> dict:
    market = snap.market.get(row["ticker"], {})
    fails = [l for l in report if l.result == "FAIL"]
    top_flags = ["Aggregate/correlation risk: NOT ASSESSED – no correlation data"]
    top_flags += [f"LIMIT FAIL – {l.name}: {l.note or f'usage {l.usage}, limit {l.limit}, headroom {l.headroom}'}"
                  for l in fails]
    if final is None:
        size_text = size_note
    elif final == 0:
        size_text = "0 (book-level limit breached – PM decision needed)"
    else:
        size_text = f"{final:.2f}% NAV ({size_note})"
    return {
        "top_flags": top_flags,
        "1_ticker_direction_date": f"{row['ticker']} {row['direction']} · {snap.pulled_at:%Y-%m-%d}"
                                   f" · idea age from {row['date_generated']}",
        "2_thesis_summary": memo["thesis_summary"],
        "3_catalyst": memo["catalyst"],
        "4_data_points": memo["data_points"],
        "5_key_risk": memo["key_risk"],
        "6_falsifier_exit": f"{memo['falsifier']} · exit level {memo['exit_level']}",
        "7_conviction_proposed": f"{memo['conviction_proposed']} – {memo['conviction_reason']}",
        "8_return_vol_liquidity": {
            "expected_return": row["expected_return"],
            "volatility": market.get("volatility", "MISSING"),
            "adv_usd": market.get("adv_usd", "MISSING"),
            "owners": {"expected_return": "analyst (idea_pipeline)",
                       "volatility/adv": "market data owner"},
        },
        "9_size": size_text,
        "9_size_pct_nav": final,
        "10_limit_report": [vars(l) for l in report],
        "11_pm_decision": "",
        "policy_version": policy["version"],
        "snapshot_id": snap.snapshot_id,
    }


def _finish(res: RunResult, agent, db: ReadOnlyDB, policy) -> RunResult:
    written = getattr(agent, "files_written", [])
    res.boundaries = {
        "S1 DB calls": 0,  # S1 never receives a database handle
        "S1 files written only allowed types": all(f.startswith(ALLOWED_S1_FILES) for f in written),
        "DB writes": 0,
        "receipts all PASS": all(r["result"] == "PASS" for r in res.receipts),
        "policy version": policy["version"],
    }
    return res


def _stop(res: RunResult, reason: str) -> RunResult:
    res.status, res.stop_reason = "STOPPED", reason
    return res
