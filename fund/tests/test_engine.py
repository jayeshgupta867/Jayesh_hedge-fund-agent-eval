"""Engine tests on a synthetic market. GitHub Actions runs these before every trading day:
if any fail, the fund does not trade that day."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fund.engine import analyst as analyst_mod  # noqa: E402
from fund.engine.analyst import GroqAnalyst, TemplateAnalyst, make_analyst  # noqa: E402
from fund.engine.cli import POLICY, run  # noqa: E402
from fund.engine.data import DataError, validate  # noqa: E402
from fund.engine.day import run_day  # noqa: E402
from fund.engine.ledger import Ledger  # noqa: E402
from fund.tests.synth import make_prices, make_universe  # noqa: E402

RULES = json.loads((POLICY / "standing_rules.json").read_text())
LIMITS = json.loads((POLICY / "limit_policy.json").read_text())["limits"]
U = make_universe()


@pytest.fixture
def prices():
    return make_prices(U)


def day(ledger, prices, i, analyst=None, rules=RULES, overrides=None):
    return run_day(ledger, prices, prices.dates[i], U, POLICY / "limit_policy.json", rules,
                   overrides or {}, analyst or TemplateAnalyst(), "test")


# ------------------------------------------------------------------ accounting

def test_nav_equals_cash_plus_positions_every_day(prices, tmp_path):
    led = Ledger.load(tmp_path, capital=1_000_000)
    for i in range(-30, 0):
        day(led, prices, i)
        assert led.nav[-1]["nav"] == pytest.approx(led.cash + sum(p["market_value"] for p in led.positions), abs=0.02)
    assert len(led.trades) > 0


def test_saving_and_reloading_daily_gives_identical_results(prices, tmp_path):
    """Live mode reloads the ledger from disk every day; it must match one continuous run."""
    continuous = Ledger.load(tmp_path / "a", capital=1_000_000)
    for i in range(-25, 0):
        day(continuous, prices, i)
    for i in range(-25, 0):
        led = Ledger.load(tmp_path / "b", capital=1_000_000)
        day(led, prices, i)
        led.save()
    reloaded = Ledger.load(tmp_path / "b")
    assert reloaded.nav_value == pytest.approx(continuous.nav_value, rel=1e-9)
    assert len(reloaded.trades) == len(continuous.trades)


def test_same_day_twice_is_a_no_op(prices, tmp_path):
    led = Ledger.load(tmp_path, capital=1_000_000)
    assert day(led, prices, -1) is not None
    n = len(led.trades)
    assert day(led, prices, -1) is None and len(led.trades) == n


def test_split_creates_no_fake_pnl(tmp_path):
    """A 4:1 split cuts the traded price, but positions are marked on adjusted prices."""
    base = make_prices(U)
    led = Ledger.load(tmp_path, capital=1_000_000)
    day(led, base, -3)
    held = led.positions[0]["ticker"]
    split = make_prices(U, split=(held, len(base.dates) - 2, 4.0))
    a, b = Ledger.load(tmp_path / "x", capital=1e6), Ledger.load(tmp_path / "y", capital=1e6)
    for led_, p_ in ((a, base), (b, split)):
        for i in (-3, -2):
            day(led_, p_, i)
    assert b.nav_value == pytest.approx(a.nav_value, rel=1e-9)


# ------------------------------------------------------------------ limits and rules

def test_every_entry_respects_position_and_sector_limits(prices, tmp_path):
    led = Ledger.load(tmp_path, capital=1_000_000)
    for i in range(-40, 0):
        rep = day(led, prices, i)
        nav = led.nav_value
        for t in rep["executed"]:
            assert abs(t["notional"]) <= LIMITS["max_position_pct_nav"] / 100 * rep["nav_before_trades"] * 1.0001
            sector = next(p["sector"] for p in led.positions if p["ticker"] == t["ticker"])
            exposure = sum(abs(p["market_value"]) for p in led.positions if p["sector"] == sector) / nav * 100
            assert exposure <= LIMITS["max_sector_pct_nav"] + 1e-6
        gross, net = led.exposures()
        assert gross <= LIMITS["max_gross_pct_nav"] + 1e-6


def test_no_trade_without_the_standing_rules(prices, tmp_path):
    strict = {**RULES, "min_conviction": 6}  # impossible bar: the PM approves nothing
    led = Ledger.load(tmp_path, capital=1_000_000)
    rep = day(led, prices, -1, rules=strict)
    assert rep["executed"] == [] and all("conviction below 6" in s["reason"] for s in rep["skipped"])


def test_vetoed_ticker_is_never_traded(prices, tmp_path):
    first = day(Ledger.load(tmp_path / "a", capital=1e6), prices, -1)
    top = first["executed"][0]["ticker"]
    led = Ledger.load(tmp_path / "b", capital=1e6)
    rep = day(led, prices, -1, overrides={"veto_tickers": [top]})
    assert top not in {t["ticker"] for t in rep["executed"]} and top in rep["screen"]["vetoed"]


def test_pm_close_override_closes_the_position(prices, tmp_path):
    led = Ledger.load(tmp_path, capital=1e6)
    day(led, prices, -2)
    t = led.positions[0]["ticker"]
    rep = day(led, prices, -1, overrides={"close_tickers": [t]})
    assert any(e["ticker"] == t and e["reason"] == "PM override: close" for e in rep["exits"])
    assert t not in led.held()


def test_stop_loss_exits_a_losing_long(prices, tmp_path):
    led = Ledger.load(tmp_path, capital=1e6)
    day(led, prices, -3)
    long_t = next(p["ticker"] for p in led.positions if p["direction"] == "LONG")
    crash = make_prices(U)
    for frame in (crash.adj, crash.close):
        frame.loc[crash.dates[-2]:, long_t] *= 0.8
    rep = day(led, crash, -2)
    assert any(e["ticker"] == long_t and e["reason"].startswith("stop loss") for e in rep["exits"])


def test_screen_never_reproposes_a_held_name(prices, tmp_path):
    led = Ledger.load(tmp_path, capital=1e6)
    for i in range(-10, 0):
        rep = day(led, prices, i)
        assert rep.get("harness", {}).get("exceptions", []) == []


# ------------------------------------------------------------------ the AI analyst

def _good_reply(row_holder):
    def chat(self, system, user):
        if "Idea row" not in user:
            raise RuntimeError("no reasons from model")
        row = json.loads(user.split("Idea row:\n")[1].split("\n\n")[0])
        return {"thesis_summary": "Trend.", "catalyst": "Trend holds.", "key_risk": "Reversal.",
                "falsifier": "Breaks the 200-day average.", "exit_level": -0.1,
                "conviction_proposed": row["conviction"], "conviction_reason": "Signal only.",
                "data_points": [{"column": "momentum_12_1", "value": row["momentum_12_1"]},
                                {"column": "vol_63d", "value": row["vol_63d"]}]}
    return chat


def test_model_drafts_that_pass_the_checks_can_trade(prices, tmp_path, monkeypatch):
    monkeypatch.setattr(GroqAnalyst, "_chat", _good_reply(None))
    rep = day(Ledger.load(tmp_path, capital=1e6), prices, -1, analyst=GroqAnalyst("k"))
    assert rep["executed"] and rep["analyst"] == "groq"
    assert any("reasons: model unavailable" in m for m in rep["analyst_log"])


def test_model_that_misquotes_data_never_trades(prices, tmp_path, monkeypatch):
    def lying(self, system, user):
        out = _good_reply(None)(self, system, user)
        out["data_points"][0]["value"] = 0.99  # wrong number, every attempt
        return out
    monkeypatch.setattr(GroqAnalyst, "_chat", lying)
    rep = day(Ledger.load(tmp_path, capital=1e6), prices, -1, analyst=GroqAnalyst("k"))
    assert rep["executed"] == []
    assert all(v == "STOPPED" for v in rep["harness"]["ideas"].values())


def test_model_outage_falls_back_to_template(prices, tmp_path, monkeypatch):
    def down(self, system, user):
        raise ConnectionError("api down")
    monkeypatch.setattr(GroqAnalyst, "_chat", down)
    rep = day(Ledger.load(tmp_path, capital=1e6), prices, -1, analyst=GroqAnalyst("k"))
    assert rep["executed"] and any("used template" in m for m in rep["analyst_log"])


def test_replay_never_uses_the_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    assert isinstance(make_analyst("replay"), TemplateAnalyst)
    assert not isinstance(make_analyst("replay"), GroqAnalyst)
    assert isinstance(make_analyst("live"), GroqAnalyst)


# ------------------------------------------------------------------ data and replay

def test_missing_benchmark_stops_everything(prices):
    prices.adj.loc[prices.dates[-1], "SPY"] = float("nan")
    with pytest.raises(DataError):
        validate(prices, list(U) + ["SPY"])


def test_replay_is_reproducible(prices, tmp_path):
    a = run("replay", days=20, prices=prices, state_root=tmp_path / "a", universe=U)
    b = run("replay", days=20, prices=prices, state_root=tmp_path / "b", universe=U)
    assert [r["nav_after"] for r in a] == [r["nav_after"] for r in b]
    assert pd.read_csv(tmp_path / "a" / "replay" / "nav.csv").shape[0] == 20
