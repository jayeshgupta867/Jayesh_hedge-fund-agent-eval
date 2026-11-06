"""Data-quality gate (v4): always trade on the last available data, and never on a glitch.

Two layers, both deterministic:

1. prepare_live  – before a live run. Drops a bar for a session that has not closed yet
   (a run during US market hours must never book intraday prices: this happened on the
   first live day, 2 Nov 2026) and stops everything if the feed is stale.
2. quarantine    – for every processed day. A ticker whose latest bar looks wrong is
   quarantined: no new trade, no mark-to-market, exits postponed and escalated to the PM.
   A one-day move above the threshold is accepted only if a second source confirms it.
   A glitch in the benchmark stops the whole day.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .data import DataError, Prices

NY = ZoneInfo("America/New_York")
BENCHMARK = "SPY"


def _drop_last(prices: Prices) -> Prices:
    return Prices(close=prices.close.iloc[:-1], adj=prices.adj.iloc[:-1],
                  volume=prices.volume.iloc[:-1], source=prices.source)


def prepare_live(prices: Prices, now_utc: datetime, cfg: dict) -> tuple[Prices, list[dict]]:
    now_ny = now_utc.astimezone(NY)
    if prices.dates[-1].date() > now_ny.date():
        raise DataError(f"latest bar {prices.dates[-1].date()} is in the future "
                        f"(clock {now_ny:%Y-%m-%d %H:%M} New York)")
    prices, notes = drop_unfinished_session(prices, now_ny, cfg)
    notes += check_freshness(prices, now_ny, cfg)
    return prices, notes


def drop_unfinished_session(prices: Prices, now_ny: datetime, cfg: dict) -> tuple[Prices, list[dict]]:
    """Never book intraday prices: a bar for today is dropped until the session has closed."""
    last = prices.dates[-1].date()
    hh, mm = (int(x) for x in str(cfg["session_close_ny"]).split(":"))
    if last == now_ny.date() and now_ny.time() < time(hh, mm):
        return _drop_last(prices), [{"check": "session closed", "result": "WARN",
                                     "note": f"{last} session still open at {now_ny:%H:%M} New York: partial "
                                             f"bar dropped, nothing is booked at intraday prices"}]
    return prices, [{"check": "session closed", "result": "PASS", "note": f"latest bar {last} is a closed session"}]


def check_freshness(prices: Prices, now_ny: datetime, cfg: dict) -> list[dict]:
    last = prices.dates[-1].date()
    age = int(np.busday_count(last, now_ny.date()))
    if age > cfg["max_stale_business_days"]:
        raise DataError(f"stale data: latest bar {last} is {age} business days old")
    return [{"check": "data freshness", "result": "PASS", "note": f"latest bar {age} business day(s) old"}]


def quarantine(prices: Prices, date: pd.Timestamp, tickers: list[str], cfg: dict,
               confirm: Callable[[str, pd.Timestamp], float | None] | None = None
               ) -> tuple[dict[str, str], list[dict]]:
    """Return ({ticker: reason} to quarantine on `date`, check notes). Uses data up to `date` only."""
    adj = prices.adj.loc[:date]
    close = prices.close.loc[:date]
    if len(adj) < 2:
        return {}, []
    q: dict[str, str] = {}
    notes: list[dict] = []
    n = int(cfg["frozen_days"])
    for t in tickers:
        if t not in adj.columns:
            continue
        a_now, a_prev = adj[t].iloc[-1], adj[t].iloc[-2]
        c_now = close[t].iloc[-1]
        if pd.isna(a_now) or pd.isna(c_now):
            continue  # missing today: already handled (no trade, mark kept)
        if a_now <= 0 or c_now <= 0:
            q[t] = "non-positive price"
            continue
        recent = close[t].iloc[-n:]
        if len(recent) == n and recent.notna().all() and recent.nunique() == 1:
            q[t] = f"price unchanged for {n} days (frozen feed)"
            continue
        if pd.isna(a_prev) or a_prev <= 0:
            continue
        move = float(a_now / a_prev - 1)
        limit = cfg["max_benchmark_move"] if t == BENCHMARK else cfg["max_one_day_move"]
        if abs(move) > limit and len(adj) >= 3:
            base = adj[t].iloc[-3]
            if base == base and base > 0 and abs(a_now / base - 1) <= limit < abs(a_prev / base - 1):
                notes.append({"check": f"one-day move {t}", "result": "PASS",
                              "note": f"{move:+.1%} reverts yesterday's outlier bar; today is consistent "
                                      f"with the day before"})
                continue
        if abs(move) > limit:
            other = confirm(t, date) if confirm else None
            if other and abs(other / float(c_now) - 1) <= cfg["confirm_tolerance"]:
                notes.append({"check": f"one-day move {t}", "result": "PASS",
                              "note": f"{move:+.1%} confirmed by a second source ({other:.2f})"})
            else:
                why = "no second source" if not other else f"second source says {other:.2f} vs {float(c_now):.2f}"
                q[t] = f"unconfirmed one-day move of {move:+.1%} ({why})"
    if BENCHMARK in q:
        raise DataError(f"benchmark {BENCHMARK} failed the data check: {q[BENCHMARK]}")
    if not q:
        notes.append({"check": "glitch scan", "result": "PASS",
                      "note": f"{len(tickers)} tickers: no frozen prices, no unconfirmed jumps"})
    return q, notes
