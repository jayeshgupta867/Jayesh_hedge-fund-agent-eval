"""U7 — position sizing. Pure arithmetic; never reads the thesis text.

size (% NAV) = risk_budget x (conviction / 5) / volatility,
capped by liquidity: value <= max_liquidation_days x max_adv_participation x ADV.
If volatility or liquidity is missing, the size is WITHHELD (never guessed).
"""
from __future__ import annotations

WITHHELD = "WITHHELD – missing volatility/liquidity"


def size_position(conviction: int, market: dict | None, nav: float, policy: dict):
    """Return (size_pct or None, note)."""
    vol = (market or {}).get("volatility")
    adv = (market or {}).get("adv_usd")
    if not isinstance(vol, (int, float)) or not isinstance(adv, (int, float)) or vol <= 0 or adv <= 0:
        return None, WITHHELD
    s = policy["sizing"]
    raw = s["risk_budget_pct_nav"] * (conviction / 5) / market["volatility"]
    liq_cap = 100 * s["max_liquidation_days"] * s["max_adv_participation"] * market["adv_usd"] / nav
    size = min(raw, liq_cap)
    note = "liquidity-capped" if liq_cap < raw else "risk-budget sized"
    return round(size, 4), note
