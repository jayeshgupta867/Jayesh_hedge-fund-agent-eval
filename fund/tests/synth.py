"""Synthetic market for engine tests: deterministic random walks, no network."""
import numpy as np
import pandas as pd

from fund.engine.data import Prices

SECTORS = ["Information Technology", "Health Care", "Financials", "Energy", "Industrials", "Consumer Staples"]


def make_universe(n: int = 36) -> dict[str, str]:
    return {f"S{i:02d}": SECTORS[i % len(SECTORS)] for i in range(n)}


def make_prices(universe: dict, days: int = 420, seed: int = 7, split: tuple | None = None) -> Prices:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-06-03", periods=days)
    cols = list(universe) + ["SPY"]
    drift = rng.normal(0, 0.45, len(cols)) / 252
    drift[-1] = 0.08 / 252
    rets = rng.normal(drift, 0.25 / np.sqrt(252), (days, len(cols)))
    adj = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=cols)
    close = adj.copy()
    if split:  # (ticker, date index, ratio): traded price drops, adjusted series does not
        t, i, ratio = split
        close.loc[close.index[i]:, t] /= ratio
    vol = pd.DataFrame(5_000_000.0, index=dates, columns=cols)
    return Prices(close=close, adj=adj, volume=vol, source="synthetic")
