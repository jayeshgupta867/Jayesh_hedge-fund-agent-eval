"""Momentum screen: the only source of trade ideas. Pure arithmetic, no AI.

For each stock on date t (using only data up to t, so no look-ahead):
- momentum_12_1: return from 252 to 21 trading days ago (skips the last month)
- pct_above_ma200: price vs its 200-day average
- vol_63d: annualised volatility of daily returns over the last 63 days
- adv_usd: average daily traded value over the last 20 days

Longs: strongest momentum and above the 200-day average.
Shorts: weakest momentum and below the 200-day average.
"""
from __future__ import annotations

import math

import pandas as pd

from .data import Prices

LOOKBACK = 252
SKIP = 21
HORIZON_MONTHS = 3


def features(prices: Prices, date: pd.Timestamp, tickers: list[str]) -> pd.DataFrame:
    adj = prices.adj.loc[:date, [t for t in tickers if t in prices.adj.columns]]
    if len(adj) < LOOKBACK + 1:
        raise ValueError(f"need {LOOKBACK + 1} days of history before {date.date()}")
    rets = adj.pct_change(fill_method=None).iloc[-63:]
    px = prices.close.loc[:date, adj.columns]
    vol = prices.volume.loc[:date, adj.columns]
    f = pd.DataFrame({
        "momentum_12_1": adj.iloc[-SKIP - 1] / adj.iloc[-LOOKBACK - 1] - 1,
        "pct_above_ma200": adj.iloc[-1] / adj.iloc[-200:].mean() - 1,
        "vol_63d": rets.std() * math.sqrt(252),
        "adv_usd": (px.iloc[-20:] * vol.iloc[-20:]).mean(),
        "price": px.iloc[-1],
    }).dropna()
    f["mom_pct"] = f["momentum_12_1"].rank(pct=True)
    return f


def conviction_from_pct(p: float) -> int:
    """Strength of the signal, mapped to the 1–5 scale the harness uses."""
    edge = max(p, 1 - p)
    return 5 if edge >= 0.95 else 4 if edge >= 0.90 else 3


def screen(prices: Prices, date: pd.Timestamp, universe: dict[str, str],
           exclude: set[str], n_long: int = 6, n_short: int = 4,
           allow_shorts: bool = True) -> list[dict]:
    f = features(prices, date, list(universe))
    f = f.drop(index=[t for t in exclude if t in f.index])
    longs = f[(f.mom_pct >= 0.8) & (f.pct_above_ma200 > 0)].nlargest(n_long, "momentum_12_1")
    shorts = (f[(f.mom_pct <= 0.2) & (f.pct_above_ma200 < 0)].nsmallest(n_short, "momentum_12_1")
              if allow_shorts else f.iloc[0:0])
    ideas = []
    for direction, block in (("LONG", longs), ("SHORT", shorts)):
        for t, r in block.iterrows():
            mom = round(float(r.momentum_12_1), 4)
            ideas.append({
                "idea_id": f"{date:%Y%m%d}-{t}",
                "ticker": t,
                "direction": direction,
                "sector": universe[t],
                "thesis": (f"12-1 momentum {mom:+.1%}, price {r.pct_above_ma200:+.1%} vs 200-day "
                           f"average, momentum percentile {r.mom_pct:.0%} of the universe"),
                # Momentum-implied proxy, not a forecast: a quarter of the trailing signal, capped
                "expected_return": round(min(abs(mom) * 0.25, 0.25), 4),
                "horizon_months": HORIZON_MONTHS,
                "conviction": conviction_from_pct(float(r.mom_pct)),
                "status": "Pending",
                "date_generated": f"{date:%Y-%m-%d}",
                "momentum_12_1": mom,
                "pct_above_ma200": round(float(r.pct_above_ma200), 4),
                "vol_63d": round(float(r.vol_63d), 4),
                "mom_percentile": round(float(r.mom_pct), 4),
                "price": round(float(r.price), 2),
                "adv_usd": round(float(r.adv_usd), 0),
            })
    return ideas
