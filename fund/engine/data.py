"""Daily prices: Yahoo Finance via yfinance, with Stooq as a fallback source.

Two series per ticker:
- close: the traded price, used for fills, shares and display
- adj:   total-return adjusted close, used for signals and for marking positions
         (so splits and dividends never create fake gains or losses)
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd


class DataError(Exception):
    """Prices are missing or incomplete: the run stops and nothing trades."""


@dataclass
class Prices:
    close: pd.DataFrame   # index: dates, columns: tickers
    adj: pd.DataFrame
    volume: pd.DataFrame
    source: str

    @property
    def dates(self) -> list[pd.Timestamp]:
        return list(self.adj.index)


def load_prices(tickers: list[str], period: str = "2y") -> Prices:
    try:
        prices = _from_yahoo(tickers, period)
    except Exception as exc:  # noqa: BLE001
        print(f"[data] Yahoo failed ({exc}); trying Stooq")
        prices = _from_stooq(tickers)
    validate(prices, tickers)
    return prices


def validate(prices: Prices, tickers: list[str], max_missing: float = 0.2) -> None:
    last = prices.adj.iloc[-1]
    missing = [t for t in tickers if t not in last.index or pd.isna(last.get(t))]
    if "SPY" in missing:
        raise DataError("benchmark SPY missing on the latest date")
    if len(missing) > max_missing * len(tickers):
        raise DataError(f"{len(missing)} of {len(tickers)} tickers missing on the latest date")


def _from_yahoo(tickers: list[str], period: str) -> Prices:
    import yfinance as yf

    raw = yf.download(tickers, period=period, auto_adjust=False, progress=False,
                      threads=True, group_by="column")
    if raw is None or raw.empty:
        raise DataError("empty download")
    close, adj, vol = raw["Close"], raw["Adj Close"], raw["Volume"]
    keep = adj.dropna(how="all").index
    return Prices(close.loc[keep], adj.loc[keep], vol.loc[keep], "yahoo")


def _from_stooq(tickers: list[str]) -> Prices:
    import requests

    close, vol = {}, {}
    for t in tickers:
        sym = t.lower().replace(".", "-") + ".us"
        r = requests.get(f"https://stooq.com/q/d/l/?s={sym}&i=d", timeout=20)
        if r.status_code != 200 or not r.text.startswith("Date"):
            continue
        df = pd.read_csv(io.StringIO(r.text), parse_dates=["Date"]).set_index("Date").iloc[-520:]
        close[t], vol[t] = df["Close"], df["Volume"]
    if not close:
        raise DataError("no data from Stooq either")
    c = pd.DataFrame(close).sort_index()
    # Stooq closes are split- and dividend-adjusted already
    return Prices(c, c.copy(), pd.DataFrame(vol).sort_index(), "stooq")
