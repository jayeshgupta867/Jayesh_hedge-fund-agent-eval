"""Book-level risk added in v4. Pure arithmetic on data up to the
decision date, so a replay can never peek at the future.

- correlation_check: an idea that replicates the existing book is concentration, not a new idea.
  Correlations are *signed* by side, so a long and a short in the same stock pair count as a
  hedge, and two longs in the same cluster count as one bet.
- liquidity: never trade more than a set share of average daily volume; cost grows with size.
- crowding_check: crowded shorts get squeezed (GameStop 2021, Volkswagen 2008).
- betas / hedge_target: the third book, a SPY hedge that protects the long/short books.
- signal_facts: numbers the analyst uses to question its input.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .data import Prices
from .screen import LOOKBACK, SKIP

HEDGE_TICKER = "SPY"
HEDGE_ID = "HEDGE"
HEDGE_SECTOR = "Index hedge"


def book_of(row: dict) -> str:
    """LONG, SHORT or HEDGE for a position or trade row."""
    if row.get("idea_id") == HEDGE_ID or row.get("sector") == HEDGE_SECTOR:
        return "HEDGE"
    return str(row.get("direction", ""))


def returns_window(prices: Prices, date: pd.Timestamp, tickers: list[str], window: int) -> pd.DataFrame:
    adj = prices.adj.loc[:date]
    cols = [t for t in dict.fromkeys(tickers) if t in adj.columns]
    return adj[cols].iloc[-(window + 1):].pct_change(fill_method=None).iloc[1:]


def correlation_check(prices: Prices, date: pd.Timestamp, ticker: str, direction: str,
                      positions: list[dict], cfg: dict) -> dict:
    """Return {result, action, rho_book, max_pair, pair_ticker, note}.

    action: none · halve · reject · escalate (could not be computed)
    """
    book = [p for p in positions if book_of(p) != "HEDGE" and p["ticker"] != ticker]
    out = {"result": "PASS", "action": "none", "rho_book": None, "max_pair": None, "pair_ticker": None}
    if not book:
        return out | {"note": "book empty: nothing to be correlated with"}
    r = returns_window(prices, date, [ticker] + [p["ticker"] for p in book], int(cfg["window_days"]))
    if ticker not in r.columns or r[ticker].count() < cfg["min_obs"]:
        return out | {"result": "NOT ASSESSED", "action": "escalate",
                      "note": f"less than {cfg['min_obs']} days of returns for {ticker}"}
    cand = r[ticker] * (1 if direction == "LONG" else -1)
    weights = {p["ticker"]: float(p["market_value"]) for p in book
               if p["ticker"] in r.columns and r[p["ticker"]].count() >= cfg["min_obs"]}
    if not weights:
        return out | {"result": "NOT ASSESSED", "action": "escalate", "note": "no return history for the book"}
    signed = {t: r[t] * (1 if w > 0 else -1) for t, w in weights.items()}
    pairs = {t: float(cand.corr(s)) for t, s in signed.items()}
    book_ret = sum(r[t].fillna(0) * w for t, w in weights.items()) / sum(abs(w) for w in weights.values())
    rho_book = float(cand.corr(book_ret))
    pair_t = max(pairs, key=pairs.get)
    rho_max = pairs[pair_t]
    worst = max(rho_book, rho_max)
    out |= {"rho_book": round(rho_book, 3), "max_pair": round(rho_max, 3), "pair_ticker": pair_t}
    if worst > cfg["reject_above"]:
        return out | {"result": "FAIL", "action": "reject",
                      "note": f"replicates the book: correlation {worst:.2f} > {cfg['reject_above']} "
                              f"(closest: {pair_t} {rho_max:.2f})"}
    if worst > cfg["halve_above"]:
        return out | {"result": "PASS", "action": "halve",
                      "note": f"concentration: correlation {worst:.2f} > {cfg['halve_above']} "
                              f"(closest: {pair_t} {rho_max:.2f}), size halved"}
    return out | {"note": f"diversifying: correlation to book {rho_book:.2f}, closest {pair_t} {rho_max:.2f}"}


def liquidity_cap_pct(adv_usd: float | None, nav: float, cfg: dict) -> float | None:
    """Largest trade in % NAV that stays within max_trade_pct_adv of average daily volume."""
    if not adv_usd or adv_usd != adv_usd or adv_usd <= 0:
        return None
    return 100 * (cfg["max_trade_pct_adv"] / 100) * adv_usd / nav


def impact_bps(notional: float, adv_usd: float | None, vol_annual: float | None, cfg: dict) -> float:
    """Square-root market impact: coefficient x daily volatility x sqrt(participation)."""
    if not adv_usd or not vol_annual or adv_usd != adv_usd or vol_annual != vol_annual:
        return 0.0
    participation = abs(notional) / adv_usd
    return 1e4 * cfg["impact_coefficient"] * (vol_annual / math.sqrt(252)) * math.sqrt(participation)


def crowding_check(short_pct_float: float | None, cfg: dict, point_in_time: bool) -> dict:
    """Short book rule. short_pct_float is a fraction (0.12 = 12% of float sold short)."""
    limit = cfg["max_short_interest_pct_float"]
    if not point_in_time:
        return {"result": "NOT ASSESSED", "action": "none",
                "note": "replay: no point-in-time short interest, crowding not checked"}
    if short_pct_float is None or short_pct_float != short_pct_float:
        return {"result": "NOT ASSESSED", "action": "escalate",
                "note": "short interest unavailable: crowding cannot be verified, PM decides"}
    pct = 100 * float(short_pct_float)
    if pct > limit:
        return {"result": "FAIL", "action": "reject",
                "note": f"crowded short: {pct:.1f}% of float sold short > {limit}% (squeeze risk)"}
    return {"result": "PASS", "action": "none", "note": f"short interest {pct:.1f}% of float"}


def betas(prices: Prices, date: pd.Timestamp, tickers: list[str], window: int) -> dict[str, float | None]:
    r = returns_window(prices, date, list(tickers) + [HEDGE_TICKER], window)
    var = r[HEDGE_TICKER].var()
    out = {}
    for t in tickers:
        if t not in r.columns or r[t].count() < window * 0.6 or not var:
            out[t] = None
        else:
            out[t] = float(r[t].cov(r[HEDGE_TICKER]) / var)
    return out


def hedge_target(positions: list[dict], beta: dict[str, float | None], nav: float, cfg: dict) -> dict:
    """SPY market value that brings the beta-adjusted net exposure to the target."""
    exposure, assumed = 0.0, []
    for p in positions:
        if book_of(p) == "HEDGE":
            continue
        b = beta.get(p["ticker"])
        if b is None:
            assumed.append(p["ticker"])
            b = 1.0
        exposure += float(p["market_value"]) * b
    target = -(exposure - cfg["target_net_beta_pct"] / 100 * nav)
    return {"book_beta_pct": round(100 * exposure / nav, 2), "target_mv": round(target, 2),
            "beta_assumed_1": assumed}


def signal_facts(prices: Prices, date: pd.Timestamp, ticker: str) -> dict:
    """Code-computed facts about the price path behind a momentum signal."""
    s = prices.adj.loc[:date, ticker].dropna()
    window = s.iloc[-LOOKBACK - 1:-SKIP]
    lr = np.log(window).diff().dropna()
    total = float(lr.sum()) if len(lr) else 0.0
    facts = {"last_day_move": round(float(s.iloc[-1] / s.iloc[-2] - 1), 4) if len(s) > 1 else None,
             "largest_day_move": None, "largest_day_date": None, "share_of_momentum_from_one_day": None}
    if len(lr):
        day = lr.abs().idxmax()
        move = float(lr[day])
        facts["largest_day_move"] = round(math.exp(move) - 1, 4)
        facts["largest_day_date"] = f"{day:%Y-%m-%d}"
        if total and np.sign(move) == np.sign(total):
            facts["share_of_momentum_from_one_day"] = round(move / total, 3)
        else:
            facts["share_of_momentum_from_one_day"] = 0.0
    return facts


def capacity_usd(positions: list[dict], adv: dict[str, float], nav: float, cfg: dict) -> float | None:
    """Fund size at which today's weights would first hit the ADV participation limit."""
    caps = []
    for p in positions:
        a = adv.get(p["ticker"])
        w = abs(float(p["market_value"])) / nav if nav else 0
        if a and a == a and w > 0:
            caps.append(a * cfg["max_trade_pct_adv"] / 100 / w)
    return round(min(caps), -5) if caps else None
