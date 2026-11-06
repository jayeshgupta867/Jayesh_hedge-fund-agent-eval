"""Paper ledger: cash, positions, trades and daily NAV, stored as CSV/JSON in the repo.

Positions are carried at market value and marked with total-return adjusted prices,
so splits and dividends never create fake P&L. Shares are informational (value / price).
Accounting identity, checked by the tests: NAV = cash + sum of position market values.

v4: every position remembers the date of its last trusted mark (mark_date). A day's move is
always measured inside ONE price download (adj[today] / adj[mark_date]), so a quarantined
glitch is skipped without losing the real move later, and splits or dividends announced
after the last run cannot create fake P&L. pending.json holds trades waiting for the PM.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

POS_COLS = ["ticker", "sector", "direction", "idea_id", "entry_date", "entry_price",
            "cost_basis", "market_value", "last_price", "mark_date"]
TRADE_COLS = ["date", "ticker", "action", "direction", "shares", "price", "notional",
              "cost", "reason", "idea_id"]
NAV_COLS = ["date", "nav", "cash", "gross_pct", "net_pct", "n_positions", "daily_pnl",
            "spy_close", "spy_index", "fund_index", "beta_net_pct", "hedge_pct"]


@dataclass
class Ledger:
    path: Path
    cash: float = 0.0
    capital: float = 0.0
    inception: str = ""
    positions: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    nav: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------ persistence
    @classmethod
    def load(cls, path: Path, capital: float = 1_000_000.0) -> "Ledger":
        path = Path(path)
        meta = path / "meta.json"
        if not meta.exists():
            return cls(path=path, cash=capital, capital=capital)
        m = json.loads(meta.read_text())
        led = cls(path=path, cash=m["cash"], capital=m["capital"], inception=m["inception"])
        led.positions = _read(path / "positions.csv")
        led.trades = _read(path / "trades.csv")
        led.nav = _read(path / "nav.csv")
        pend = path / "pending.json"
        led.pending = json.loads(pend.read_text()) if pend.exists() else []
        return led

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "meta.json").write_text(json.dumps(
            {"cash": self.cash, "capital": self.capital, "inception": self.inception}, indent=2))
        pd.DataFrame(self.positions, columns=POS_COLS).to_csv(self.path / "positions.csv", index=False)
        pd.DataFrame(self.trades, columns=TRADE_COLS).to_csv(self.path / "trades.csv", index=False)
        pd.DataFrame(self.nav, columns=NAV_COLS).to_csv(self.path / "nav.csv", index=False)
        (self.path / "pending.json").write_text(json.dumps(self.pending, indent=1, default=str))

    # ------------------------------------------------------------ state
    @property
    def last_date(self) -> str | None:
        return self.nav[-1]["date"] if self.nav else None

    @property
    def nav_value(self) -> float:
        return self.cash + sum(p["market_value"] for p in self.positions)

    def held(self) -> set[str]:
        return {p["ticker"] for p in self.positions}

    def exposures(self) -> tuple[float, float]:
        nav = self.nav_value
        gross = sum(abs(p["market_value"]) for p in self.positions) / nav * 100
        net = sum(p["market_value"] for p in self.positions) / nav * 100
        return gross, net

    def as_positions_risk(self) -> list[dict]:
        """The book in the shape the harness expects (positions_risk table)."""
        nav = self.nav_value
        return [{"ticker": p["ticker"], "sector": p["sector"], "direction": p["direction"],
                 "market_value": round(p["market_value"], 2),
                 "pct_nav": round(p["market_value"] / nav * 100, 4),
                 "var_95": None, "settlement_status": "Settled"} for p in self.positions]

    # ------------------------------------------------------------ actions
    def mark(self, adj: pd.DataFrame, close: pd.DataFrame, date: pd.Timestamp, skip: set[str] = frozenset()) -> list[str]:
        """Mark every position from its last trusted mark to `date`. Returns tickers left unmarked."""
        stale = []
        d = f"{date:%Y-%m-%d}"
        for p in self.positions:
            t = p["ticker"]
            since = p.get("mark_date") or self.last_date
            now = adj.at[date, t] if t in adj.columns else None
            then = adj.at[pd.Timestamp(since), t] if (t in adj.columns and pd.Timestamp(since) in adj.index) else None
            if t in skip or now is None or then is None or now != now or then != then or then <= 0:
                stale.append(t)  # keep the last trusted mark
                continue
            p["market_value"] *= float(now / then)
            p["mark_date"] = d
            c = close.at[date, t] if t in close.columns else None
            if c is not None and c == c:
                p["last_price"] = float(c)
        return stale

    def open(self, date: str, idea: dict, pct_nav: float, price: float, cost_bps: float,
             reason: str = "standing rules: memo passed") -> dict:
        sign = 1 if idea["direction"] == "LONG" else -1
        notional = sign * pct_nav / 100 * self.nav_value
        cost = abs(notional) * cost_bps / 10_000
        self.cash -= notional + cost
        self.positions.append({
            "ticker": idea["ticker"], "sector": idea["sector"], "direction": idea["direction"],
            "idea_id": idea["idea_id"], "entry_date": date, "entry_price": price,
            "cost_basis": notional, "market_value": notional, "last_price": price, "mark_date": date})
        return self._trade(date, idea["ticker"], "BUY" if sign > 0 else "SELL SHORT",
                           idea["direction"], notional, price, cost, reason, idea["idea_id"])

    def set_hedge(self, date: str, ticker: str, sector: str, hedge_id: str, target_mv: float,
                  price: float, cost_bps: float, reason: str) -> list[dict]:
        """Move the hedge position to `target_mv` (negative = short). Returns the trades."""
        h = next((p for p in self.positions if p["idea_id"] == hedge_id), None)
        trades = []
        if h and (abs(target_mv) < 1e-6 or (h["market_value"] > 0) != (target_mv > 0)):
            trades.append(self.close(date, h["ticker"], price, cost_bps, reason))
            h = None
        if abs(target_mv) < 1e-6:
            return trades
        if h is None:
            idea = {"ticker": ticker, "sector": sector, "direction": "LONG" if target_mv > 0 else "SHORT",
                    "idea_id": hedge_id}
            trades.append(self.open(date, idea, abs(target_mv) / self.nav_value * 100, price, cost_bps, reason))
            return trades
        delta = target_mv - h["market_value"]
        cost = abs(delta) * cost_bps / 10_000
        self.cash -= delta + cost
        h["market_value"] += delta
        h["cost_basis"] += delta
        h["last_price"] = price
        action = "HEDGE ADD" if abs(target_mv) > abs(target_mv - delta) else "HEDGE REDUCE"
        trades.append(self._trade(date, ticker, action, h["direction"], delta, price, cost, reason, hedge_id))
        return trades

    def close(self, date: str, ticker: str, price: float, cost_bps: float, reason: str) -> dict:
        p = next(x for x in self.positions if x["ticker"] == ticker)
        cost = abs(p["market_value"]) * cost_bps / 10_000
        self.cash += p["market_value"] - cost
        self.positions.remove(p)
        return self._trade(date, ticker, "SELL" if p["direction"] == "LONG" else "BUY TO COVER",
                           p["direction"], -p["market_value"], price, cost, reason, p["idea_id"])

    def _trade(self, date, ticker, action, direction, notional, price, cost, reason, idea_id) -> dict:
        t = {"date": date, "ticker": ticker, "action": action, "direction": direction,
             "shares": round(abs(notional) / price, 2) if price else None, "price": round(price, 2),
             "notional": round(notional, 2), "cost": round(cost, 2), "reason": reason, "idea_id": idea_id}
        self.trades.append(t)
        return t


def _read(f: Path) -> list[dict]:
    if not f.exists() or f.stat().st_size == 0:
        return []
    df = pd.read_csv(f)
    return df.where(pd.notna(df), None).to_dict("records")
