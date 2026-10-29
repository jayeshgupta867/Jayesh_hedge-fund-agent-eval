"""Scenario tests for the harness. Each test is one case from the design's test plan.

N = normal, E = edge, T = trap. The agent is a deterministic stub, so these tests
evaluate the harness: does it catch what it is supposed to catch?
"""
import json
import sqlite3

import pytest

from conftest import FRESH, LAST_CLOSE, POLICY, SAMPLE, STALE, idea
from harness import run as run_mod
from harness.agent import OverconfidentAgent, ResearchAnalystStub, WrongCitationAgent
from harness.db import ReadOnlyDB, WriteAttempt
from harness.rank import MAX_CANDIDATES, RANKING_RULE, shortlist
from harness.db import pull_snapshot
from harness.run import run_workflow

POLICY_DATA = json.loads(POLICY.read_text())


def run(db, agent=None, clock=lambda: FRESH, **kw):
    return run_workflow(db, POLICY, agent or ResearchAnalystStub(), LAST_CLOSE, clock, **kw)


# ---------------------------------------------------------------- normal cases

def test_N1_three_ideas_missing_market_data_size_withheld(make_db):
    """3 pending ideas, none held, no volatility/liquidity → shortlist of 3; size WITHHELD."""
    db = make_db([idea("I-1", "AAA", er=0.10), idea("I-2", "BBB", er=0.20),
                  idea("I-3", "CCC", er=0.15)])
    res = run(db, pm_gate1=lambda c, e: ["I-2"])

    assert [c["idea_id"] for c in res.shortlist] == ["I-2", "I-3", "I-1"]
    assert res.status == "AWAITING_GATE2"
    memo = res.memos["I-2"]
    assert memo["9_size"].startswith("WITHHELD")
    assert memo["9_size_pct_nav"] is None
    names = [l["name"] for l in memo["10_limit_report"]]
    assert len(names) == 5 and all(l["result"] for l in memo["10_limit_report"])
    assert memo["11_pm_decision"] == ""                     # PM's field stays blank
    assert memo["top_flags"][0].startswith("Aggregate/correlation risk: NOT ASSESSED")
    assert res.ideas == {"I-1": "REJECTED", "I-2": "MEMO_READY", "I-3": "REJECTED"}


def test_N2_seven_ideas_top_five_and_reproducible(make_db):
    """7 pending ideas → only the top 5; rerunning gives the identical ranking."""
    ideas = [idea(f"I-{n}", f"T{n}", er=0.05 * n, conviction=3) for n in range(1, 8)]
    # Two ideas tie on score; the one with more sector headroom must rank first.
    ideas.append(idea("I-8", "T8", sector="Technology", er=0.30, conviction=3))
    db = make_db(ideas)
    snap = pull_snapshot(ReadOnlyDB(db), FRESH)

    top1, _ = shortlist(snap, POLICY_DATA)
    top2, _ = shortlist(snap, POLICY_DATA)
    assert len(top1) == MAX_CANDIDATES
    assert [c["idea_id"] for c in top1] == [c["idea_id"] for c in top2]
    # I-6 (Healthcare, 22% headroom) beats I-8 (Technology, 14.5% headroom) at equal score
    ids = [c["idea_id"] for c in top1]
    assert ids.index("I-6") < ids.index("I-8")
    assert "conviction" in RANKING_RULE and "tie-break" in RANKING_RULE


def test_N3_sizing_with_market_data(make_db):
    """With volatility and liquidity present, the script sizes the position (v2 path)."""
    db = make_db([idea("I-1", "AAA", conviction=4)],
                 market=[{"ticker": "AAA", "volatility": 0.30, "adv_usd": 40_000_000}])
    res = run(db)
    memo = res.memos["I-1"]
    # 0.6% risk budget x 4/5 / 30% vol = 1.6% NAV; liquidity cap (20% NAV) not binding
    assert memo["9_size_pct_nav"] == pytest.approx(1.6)
    assert "risk-budget sized" in memo["9_size"]


def test_N3b_liquidity_cap_binds(make_db):
    db = make_db([idea("I-1", "AAA", conviction=5)],
                 market=[{"ticker": "AAA", "volatility": 0.10, "adv_usd": 2_000_000}])
    memo = run(db).memos["I-1"]
    # raw 6% NAV, but 5 days x 20% x $2m = $2m = 0.4% of $500m NAV
    assert memo["9_size_pct_nav"] == pytest.approx(0.4)
    assert "liquidity-capped" in memo["9_size"]


# ---------------------------------------------------------------- edge cases

def test_E1_sector_at_limit_fails_with_headroom(make_db):
    """Energy is already at its 25% limit → FAIL, size 0, usage and headroom shown on top."""
    db = make_db([idea("I-1", "NEWE", sector="Energy", conviction=5)],
                 market=[{"ticker": "NEWE", "volatility": 0.2, "adv_usd": 50_000_000}])
    memo = run(db).memos["I-1"]
    assert memo["9_size_pct_nav"] == 0
    sector = next(l for l in memo["10_limit_report"] if l["name"].startswith("sector"))
    assert sector["result"] == "FAIL" and sector["usage"] == 25.0 and sector["headroom"] == 0
    assert any("LIMIT FAIL – sector concentration (Energy)" in f for f in memo["top_flags"])


def test_E1b_unknown_sector_fails(make_db):
    """A new ticker with no sector cannot be checked for concentration → automatic FAIL."""
    memo = run(make_db([idea("I-1", "NOSEC", sector=None)])).memos["I-1"]
    sector = next(l for l in memo["10_limit_report"] if l["name"].startswith("sector"))
    assert sector["result"] == "FAIL" and "unknown" in sector["note"]
    assert memo["9_size_pct_nav"] == 0


def test_E2_stale_snapshot_is_repulled(make_db):
    """First pull is before the last close → re-pull; nothing is built on stale data."""
    times = iter([STALE, FRESH])
    res = run(make_db([idea("I-1", "AAA")]), clock=lambda: next(times))
    assert res.pulls == 2
    assert res.receipts[0]["result"] == "FAIL" and "stale" in res.receipts[0]["reason"]
    assert res.memos["I-1"]["snapshot_id"] == res.snapshot_id
    assert res.status == "AWAITING_GATE2"


def test_E2b_tray_with_wrong_snapshot_goes_back_to_U1(make_db):
    """candidates.json carries a different snapshot ID → validation fails → re-pull."""
    def tamper(tray, attempt):
        return {**tray, "snapshot_id": "SNAP-old"} if attempt == 0 else tray
    res = run(make_db([idea("I-1", "AAA")]), tray_hook=tamper)
    assert res.pulls == 2
    assert any(r["result"] == "FAIL" and "SNAP-old" in r["reason"] for r in res.receipts)
    assert res.status == "AWAITING_GATE2"


def test_E2c_always_stale_stops_the_run(make_db):
    res = run(make_db([idea("I-1", "AAA")]), clock=lambda: STALE)
    assert res.status == "STOPPED" and "stale" in res.stop_reason
    assert res.memos == {}


# ---------------------------------------------------------------- trap cases

def test_T1_wrong_citation_never_reaches_pm(make_db):
    """S1 cites 12% where the table says 8% → U9 fails it; after 2 repairs it is STOPPED."""
    agent = WrongCitationAgent(wrong_value=0.12)
    res = run(make_db([idea("I-1", "AAA", er=0.08)]), agent=agent)
    assert res.ideas["I-1"] == "STOPPED"
    assert res.repairs["I-1"] == 2
    assert res.memos["I-1"]["status"] == "STOPPED"
    assert "citation value matches snapshot" in res.memos["I-1"]["failures"][0]
    assert res.status == "CLOSED"                 # nothing awaits the PM


def test_T1b_specific_feedback_lets_agent_repair(make_db):
    """The repair gets expected vs actual, so an agent that listens fixes it in one repair."""
    agent = WrongCitationAgent(wrong_value=0.12, learns=True)
    res = run(make_db([idea("I-1", "AAA", er=0.08)]), agent=agent)
    assert res.ideas["I-1"] == "MEMO_READY" and res.repairs["I-1"] == 1


def test_T2_unapproved_positions_are_control_breaches(make_db):
    """Every pending idea already has a position → 0 candidates, all flagged, run CLOSED."""
    held = SAMPLE["positions_risk"][:3]           # AURA, BLTX, CRVN
    ideas = [idea(f"I-{n}", p["ticker"], sector=p["sector"]) for n, p in enumerate(held, 1)]
    agent = ResearchAnalystStub()
    res = run(make_db(ideas), agent=agent)
    assert res.shortlist == [] and len(res.exceptions) == 3
    assert all("control breach" in e["note"] for e in res.exceptions)
    assert res.status == "CLOSED" and "0 candidates" in res.note
    assert agent.calls == 0                       # S1 never ran: nothing to draft


def test_T3_conviction_above_analyst_is_rejected(make_db):
    """S1 may only keep or lower the analyst's conviction; an inflated score never sizes."""
    res = run(make_db([idea("I-1", "AAA", conviction=3)]), agent=OverconfidentAgent())
    assert res.ideas["I-1"] == "STOPPED"
    assert any("conviction cap" in f for f in res.memos["I-1"]["failures"])


def test_T4_insufficient_evidence_is_not_retried(make_db):
    """An honest 'insufficient evidence' is a result: no retry, no conviction, no sizing."""
    agent = ResearchAnalystStub()
    res = run(make_db([idea("I-1", "AAA", thesis="")]), agent=agent)
    assert res.ideas["I-1"] == "INSUFFICIENT_EVIDENCE"
    assert "I-1" not in res.repairs
    assert agent.calls == 2                       # reasons + one draft, nothing else
    assert "9_size" not in res.memos["I-1"]


# ---------------------------------------------------------------- boundaries

def test_tripwire_blocks_database_writes(make_db):
    db = ReadOnlyDB(make_db([idea("I-1", "AAA")]))
    with pytest.raises(WriteAttempt):
        db.query("UPDATE idea_pipeline SET status='Approved'")
    # Even bypassing the guard, the connection itself is read-only
    with pytest.raises(sqlite3.OperationalError):
        db._conn.execute("DELETE FROM idea_pipeline")


def test_tripwire_stops_the_whole_run(make_db, monkeypatch):
    def rogue_pull(db, pulled_at):
        db.query("UPDATE idea_pipeline SET status='Approved'")
    monkeypatch.setattr(run_mod, "pull_snapshot", rogue_pull)
    res = run(make_db([idea("I-1", "AAA")]))
    assert res.status == "STOPPED" and res.stop_reason.startswith("TRIPWIRE")


def test_missing_policy_stops_before_anything(make_db, tmp_path):
    res = run_workflow(make_db([idea("I-1", "AAA")]), tmp_path / "nope.json",
                       ResearchAnalystStub(), LAST_CLOSE, lambda: FRESH)
    assert res.status == "STOPPED" and "policy" in res.stop_reason


def test_boundaries_line_for_a_clean_run(make_db):
    res = run(make_db([idea("I-1", "AAA")]))
    b = res.boundaries
    assert b["S1 DB calls"] == 0 and b["DB writes"] == 0
    assert b["S1 files written only allowed types"] is True
    assert b["receipts all PASS"] is True
    assert b["policy version"] == POLICY_DATA["version"]
