"""Read-side helpers shared by the dashboard and the tests (pandas only)."""
from __future__ import annotations

import pandas as pd

from .risk import book_of

BOOKS = ["LONG", "SHORT", "HEDGE"]


def pnl_by_book(positions: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """P&L per book since inception = cash flows of its trades + market value still held.

    Cash flow of a trade = -(notional) - cost (a buy spends, a sale or short receives).
    The three books add up exactly to NAV minus starting capital.
    """
    rows = {b: {"book": b, "realised_and_costs": 0.0, "open_value": 0.0, "open_positions": 0, "trades": 0}
            for b in BOOKS}
    for t in trades.to_dict("records") if not trades.empty else []:
        b = book_of(t)
        if b in rows:
            rows[b]["realised_and_costs"] += -float(t["notional"]) - float(t["cost"])
            rows[b]["trades"] += 1
    for p in positions.to_dict("records") if not positions.empty else []:
        b = book_of(p)
        if b in rows:
            rows[b]["open_value"] += float(p["market_value"])
            rows[b]["open_positions"] += 1
    out = pd.DataFrame(rows.values())
    out["pnl"] = out["realised_and_costs"] + out["open_value"]
    return out[["book", "pnl", "open_positions", "trades"]]
