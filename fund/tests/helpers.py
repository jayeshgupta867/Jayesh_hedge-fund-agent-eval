"""Shared helpers for the engine, v4 and red-team tests."""
import json
from pathlib import Path

import pandas as pd

from fund.engine.analyst import GroqAnalyst, TemplateAnalyst
from fund.engine.cli import POLICY
from fund.engine.data import MarketContext
from fund.engine.day import run_day
from fund.engine.ledger import Ledger
from fund.engine.policy import load_rules

RULES = load_rules(POLICY / "standing_rules.json")
LIMIT_FILE = POLICY / "limit_policy.json"
LIMITS = json.loads(LIMIT_FILE.read_text())["limits"]
CLUSTER = ["S00", "S06", "S12", "S18", "S24"]


def ledger(tmp_path, name="a") -> Ledger:
    return Ledger.load(Path(tmp_path) / name, capital=1_000_000)


def step(led, prices, i, universe, analyst=None, rules=RULES, overrides=None, mode="test",
         ctx=None, approvals=None):
    return run_day(led, prices, prices.dates[i], universe, LIMIT_FILE, rules, overrides or {},
                   analyst or TemplateAnalyst(), mode, ctx or MarketContext(), approvals)


def live_ctx(short_interest=0.02, confirm=None) -> MarketContext:
    return MarketContext(short_interest=lambda t: short_interest,
                         confirm_close=confirm or (lambda t, d: None), point_in_time=True)


def scripted_groq(memo_fn=None, challenge_fn=None, reasons_fn=None) -> GroqAnalyst:
    """A GroqAnalyst whose 'model' replies are scripted. Each fn gets the parsed input."""
    a = GroqAnalyst("test-key")

    def chat(system, user):
        if user.startswith("Idea row:"):
            if not memo_fn:
                raise ConnectionError("no memo script")
            row = json.loads(user.split("Idea row:\n")[1].split("\n\n")[0])
            return memo_fn(row)
        if user.startswith("Idea:") and "FACTS" in user:
            if not challenge_fn:
                raise ConnectionError("no challenge script")
            return challenge_fn(user)
        if reasons_fn:
            return reasons_fn(user)
        raise ConnectionError("no reasons script")

    a._chat = chat
    return a


def honest_memo(row):
    return {"thesis_summary": "Trend.", "catalyst": "Trend holds.", "key_risk": "Reversal.",
            "falsifier": "Breaks the 200-day average.", "exit_level": -0.1,
            "conviction_proposed": row["conviction"], "conviction_reason": "Signal only.",
            "data_points": [{"column": "momentum_12_1", "value": row["momentum_12_1"]},
                            {"column": "vol_63d", "value": row["vol_63d"]}]}


def poison_bar(prices, ticker, i, factor):
    """A glitch: one bar of `ticker` multiplied by `factor` in both price series."""
    for frame in (prices.adj, prices.close):
        frame.loc[prices.dates[i], ticker] *= factor


def executed_tickers(rep) -> set[str]:
    return {t["ticker"] for t in rep["executed"]}


def trade_size_pct(rep, trade) -> float:
    return abs(trade["notional"]) / rep["nav_before_trades"] * 100


def frame_equal(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    return a.reset_index(drop=True).equals(b.reset_index(drop=True))
