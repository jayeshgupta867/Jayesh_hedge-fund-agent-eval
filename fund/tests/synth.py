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


def make_factor_prices(universe: dict, cluster: list[str], days: int = 420, seed: int = 11,
                       cluster_corr: float = 0.95, beta: float = 1.0) -> Prices:
    """Market with a common factor (SPY) and a tightly correlated, strongly trending cluster.

    Every stock has market beta `beta`; the cluster shares an extra factor so its members are
    near-copies of each other (like the five chip stocks bought on the first live day).
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-06-03", periods=days)
    cols = list(universe) + ["SPY"]
    mkt = rng.normal(0.08 / 252, 0.15 / np.sqrt(252), days)
    clus = rng.normal(0.9 / 252, 0.30 / np.sqrt(252), days)
    rets = {}
    for t in universe:
        idio = rng.normal(rng.normal(0, 0.2) / 252, 0.20 / np.sqrt(252), days)
        if t in cluster:
            w = np.sqrt(cluster_corr)
            idio = w * clus + np.sqrt(1 - cluster_corr) * rng.normal(0, 0.30 / np.sqrt(252), days)
        rets[t] = beta * mkt + idio
    rets["SPY"] = mkt
    adj = pd.DataFrame({c: 100 * np.exp(np.cumsum(rets[c])) for c in cols}, index=dates)
    vol = pd.DataFrame(5_000_000.0, index=dates, columns=cols)
    return Prices(close=adj.copy(), adj=adj, volume=vol, source="synthetic")
