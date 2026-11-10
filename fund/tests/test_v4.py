"""v4 features working as intended (the red-team file tests that they cannot be abused)."""
import json

import pandas as pd
import pytest

from fund.engine import approvals as appr
from fund.engine.cli import POLICY, run
from fund.engine.ledger import NAV_COLS, Ledger
from fund.engine.policy import load_limit_policy
from fund.engine.report import pnl_by_book
from fund.tests.helpers import (CLUSTER, RULES, executed_tickers, honest_memo, ledger, live_ctx,
                                poison_bar, scripted_groq, step)
from fund.tests.synth import make_factor_prices, make_prices, make_universe

U = make_universe()


@pytest.fixture
def prices():
    return make_prices(U)


def test_pm_approval_books_the_queued_trade_at_or_below_the_approved_size(prices, tmp_path):
    esc = scripted_groq(memo_fn=honest_memo,
                        challenge_fn=lambda u: {"challenges": [{"issue": "check", "action": "escalate"}]})
    led = ledger(tmp_path)
    step(led, prices, -2, U, analyst=esc, mode="live", ctx=live_ctx())
    item = led.pending[0]
    approvals = {"items": [{"idea_id": item["idea_id"], "token": appr.token(item), "decision": "approve"}],
                 "trusted": True, "warning": None}
    rep = step(led, prices, -1, U, analyst=esc, mode="live", ctx=live_ctx(), approvals=approvals)
    booked = [t for t in rep["executed"] if t["reason"].startswith("PM approved")]
    assert [t["ticker"] for t in booked] == [item["ticker"]]
    assert abs(booked[0]["notional"]) / rep["nav_before_trades"] * 100 <= item["pct_nav"] + 1e-6
    assert rep["approvals"][0]["result"].startswith("booked")


def test_pm_reject_drops_the_trade(prices, tmp_path):
    esc = scripted_groq(memo_fn=honest_memo,
                        challenge_fn=lambda u: {"challenges": [{"issue": "check", "action": "escalate"}]})
    led = ledger(tmp_path)
    step(led, prices, -2, U, analyst=esc, mode="live", ctx=live_ctx())
    item = led.pending[0]
    approvals = {"items": [{"idea_id": item["idea_id"], "token": appr.token(item), "decision": "reject"}],
                 "trusted": True, "warning": None}
    rep = step(led, prices, -1, U, analyst=esc, mode="live", ctx=live_ctx(), approvals=approvals)
    assert "reject" in rep["approvals"][0]["result"]
    assert not any(t["reason"].startswith("PM approved") for t in rep["executed"])


def test_moderate_correlation_halves_the_size(tmp_path):
    p = make_factor_prices(U, CLUSTER, cluster_corr=0.72)
    rep = step(ledger(tmp_path), p, -1, U)
    halved = [d for d in rep["decisions"].values() if (d.get("correlation") or {}).get("action") == "halve"]
    assert halved, "expected at least one idea halved for concentration"
    for d in halved:
        assert 0.70 < max(d["correlation"]["rho_book"], d["correlation"]["max_pair"]) <= 0.85


def test_hedge_brings_beta_adjusted_net_inside_the_band(tmp_path):
    p = make_factor_prices(U, CLUSTER, beta=1.2)
    led = ledger(tmp_path)
    for i in range(-5, 0):
        rep = step(led, p, i, U)
        h = rep["hedge"]
        assert abs(h["beta_net_after_pct"]) <= RULES["hedge"]["rebalance_band_pct"] + 1e-6
    hedge = [x for x in led.positions if x["idea_id"] == "HEDGE"]
    assert hedge and hedge[0]["ticker"] == "SPY"
    assert led.nav[-1]["nav"] == pytest.approx(led.cash + sum(x["market_value"] for x in led.positions), abs=0.02)


def test_hedge_can_be_switched_off(tmp_path):
    p = make_factor_prices(U, CLUSTER, beta=1.2)
    led = ledger(tmp_path)
    rep = step(led, p, -1, U, rules={**RULES, "hedge": {**RULES["hedge"], "enabled": False}})
    assert rep["hedge"] is None and not any(x["idea_id"] == "HEDGE" for x in led.positions)


def test_books_add_up_to_total_pnl(tmp_path):
    p = make_factor_prices(U, CLUSTER, beta=1.2)
    led = ledger(tmp_path)
    for i in range(-30, 0):
        step(led, p, i, U)
    led.save()
    books = pnl_by_book(pd.read_csv(led.path / "positions.csv"), pd.read_csv(led.path / "trades.csv"))
    assert set(books["book"]) == {"LONG", "SHORT", "HEDGE"}
    assert books["pnl"].sum() == pytest.approx(led.nav_value - led.capital, abs=1.0)


def test_a_quarantined_day_is_caught_up_without_losing_the_real_move(prices, tmp_path):
    """Glitch on day -2 only: day -1's mark must equal a run that never saw the glitch."""
    clean = make_prices(U)
    a, b = ledger(tmp_path, "a"), ledger(tmp_path, "b")
    step(a, clean, -3, U)
    step(b, prices, -3, U)
    held = a.positions[0]["ticker"]
    poison_bar(prices, held, -2, 1.7)
    step(a, clean, -2, U)
    step(b, prices, -2, U)
    assert held in b.held()
    mv = lambda led: next(x["market_value"] for x in led.positions if x["ticker"] == held)
    step(a, clean, -1, U)
    step(b, prices, -1, U)
    assert held in a.held() and held in b.held()
    assert mv(b) == pytest.approx(mv(a), rel=1e-9)


def test_v3_state_without_mark_dates_loads_and_marks(prices, tmp_path):
    """The live fund was started by v3: its positions.csv has no mark_date column."""
    led = ledger(tmp_path)
    step(led, prices, -3, U, rules={**RULES, "hedge": {**RULES["hedge"], "enabled": False}})
    led.save()
    pos = pd.read_csv(led.path / "positions.csv").drop(columns=["mark_date"])
    pos.to_csv(led.path / "positions.csv", index=False)
    nav = pd.read_csv(led.path / "nav.csv")[[c for c in NAV_COLS if c not in ("beta_net_pct", "hedge_pct")]]
    nav.to_csv(led.path / "nav.csv", index=False)
    (led.path / "pending.json").unlink()
    old = Ledger.load(led.path)
    before = {x["ticker"]: x["market_value"] for x in old.positions}
    step(old, prices, -2, U)
    d0, d1 = prices.dates[-3], prices.dates[-2]
    for x in old.positions:
        if x["ticker"] in before and x["entry_date"] < f"{d1:%Y-%m-%d}":
            ratio = prices.adj.at[d1, x["ticker"]] / prices.adj.at[d0, x["ticker"]]
            assert x["market_value"] == pytest.approx(before[x["ticker"]] * ratio, rel=1e-9)


def test_live_run_after_the_close_books_today(prices, tmp_path):
    now = prices.dates[-1].tz_localize("UTC") + pd.Timedelta(hours=22, minutes=30)
    reps = run("live", prices=prices, state_root=tmp_path, universe=U, ctx=live_ctx(), now=now.to_pydatetime(),
               approvals={"items": [], "trusted": True, "warning": None})
    assert [r["date"] for r in reps] == [f"{prices.dates[-1]:%Y-%m-%d}"]
    assert json.loads((tmp_path / "live" / "pending.json").read_text()) == []


def test_report_says_which_analyst_actually_wrote_the_memos(prices, tmp_path):
    rep = step(ledger(tmp_path), prices, -1, U, analyst=scripted_groq(memo_fn=honest_memo))
    assert rep["analyst"] == "groq" and rep["analyst_used"] == "model"


def test_model_errors_are_logged_with_a_reason_but_no_secret(prices, tmp_path):
    class Resp:
        status_code = 401

        def json(self):
            return {"error": {"message": "Invalid API Key"}}

    class HTTPError(Exception):
        response = Resp()

    def fail(row):
        raise HTTPError()

    rep = step(ledger(tmp_path), prices, -1, U, analyst=scripted_groq(memo_fn=fail))
    assert any("HTTP 401: Invalid API Key" in m for m in rep["analyst_log"])
    assert not any("test-key" in m for m in rep["analyst_log"])


def test_liquidity_cap_binds_for_a_thin_stock(prices, tmp_path):
    thin = make_prices(U)
    thin.volume.loc[:, :] = 300.0  # about $30k a day traded
    rep = step(ledger(tmp_path), thin, -1, U)
    assert rep["executed"]
    for t in rep["executed"]:
        adv = float((thin.close[t["ticker"]].iloc[-20:] * 300).mean())
        assert abs(t["notional"]) <= 0.03 * (adv + 1)  # the screen rounds ADV to whole dollars
        assert abs(t["notional"]) / rep["nav_before_trades"] < 0.01


def test_every_day_report_records_book_checks(prices, tmp_path):
    rep = step(ledger(tmp_path), prices, -1, U)
    assert rep["decisions"]
    names = {c["check"] for d in rep["decisions"].values() for c in d["checks"]}
    assert {"limits (harness)", "liquidity", "correlation with book", "analyst challenge"} <= names
    assert any(c["check"] == "glitch scan" for c in rep["data_checks"])
    assert rep["capacity_usd"] is None or rep["capacity_usd"] > 0


def test_policy_has_the_v4_sections():
    pol = load_limit_policy(POLICY / "limit_policy.json")
    assert pol["version"] == "fund-2"
    assert pol["correlation"]["halve_above"] == 0.70 and pol["liquidity"]["max_trade_pct_adv"] == 3.0
       # The PM edits this file in normal use, so check its shape, not that it is empty.
    approvals = json.loads((POLICY / "pm_approvals.json").read_text())["approvals"]
    assert isinstance(approvals, list)
    for a in approvals:
        assert {"idea_id", "token", "decision"} <= a.keys() and a["decision"] in {"approve", "reject"}

def test_model_default_is_not_the_retired_one(monkeypatch):
    from fund.engine.analyst import DEFAULT_MODEL, GroqAnalyst

    monkeypatch.setenv("GROQ_MODEL", "")  # an unset repository variable arrives as an empty string
    assert GroqAnalyst("k").model == DEFAULT_MODEL != "llama-3.3-70b-versatile"
    monkeypatch.setenv("GROQ_MODEL", "some/other-model")
    assert GroqAnalyst("k").model == "some/other-model"
