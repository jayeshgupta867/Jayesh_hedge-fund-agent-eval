"""U8 — limit check against the fund's book and the PM-owned limit policy.

The check *informs* sizing: it caps the proposed size to the remaining headroom.
If a book-level limit is already used up, the size becomes 0 and the limit FAILs,
with current usage and headroom shown so the PM can decide (e.g. cut another position).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LimitLine:
    name: str
    result: str          # PASS / FAIL / NOT ASSESSED
    usage: float | None  # % NAV before this trade
    limit: float | None
    headroom: float | None
    note: str = ""


def book_exposures(positions: list[dict]) -> dict:
    gross = sum(abs(p["pct_nav"]) for p in positions)
    net = sum(p["pct_nav"] for p in positions)
    by_sector: dict[str, float] = {}
    for p in positions:
        by_sector[p["sector"]] = by_sector.get(p["sector"], 0.0) + abs(p["pct_nav"])
    return {"gross": gross, "net": net, "sector": by_sector}


def sector_headroom(sector: str | None, positions: list[dict], policy: dict) -> float:
    if not sector:
        return float("-inf")
    used = book_exposures(positions)["sector"].get(sector, 0.0)
    return policy["limits"]["max_sector_pct_nav"] - used


def check_limits(
    idea: dict, size_pct: float | None, positions: list[dict], policy: dict
) -> tuple[float | None, list[LimitLine]]:
    """Return (final size in % NAV or None if withheld, limit report)."""
    lim = policy["limits"]
    exp = book_exposures(positions)
    sign = 1 if idea["direction"] == "LONG" else -1
    lines: list[LimitLine] = []

    # Headroom for each limit (in % NAV, positive = room left for this trade)
    pos_room = lim["max_position_pct_nav"]
    sector = idea.get("sector")
    if sector:
        sec_used = exp["sector"].get(sector, 0.0)
        sec_room = lim["max_sector_pct_nav"] - sec_used
    else:
        sec_used, sec_room = None, None
    gross_room = lim["max_gross_pct_nav"] - exp["gross"]
    net_room = lim["max_net_pct_nav"] - sign * exp["net"]

    rooms = [pos_room, gross_room, net_room] + ([sec_room] if sec_room is not None else [])
    book_breach = sector is None or min(rooms) <= 0

    final = size_pct
    if book_breach:
        final = 0.0
    elif size_pct is not None:
        final = round(min([size_pct] + rooms), 4)

    def line(name, used, limit, room):
        breached = room is not None and room <= 0
        return LimitLine(name, "FAIL" if breached else "PASS", used, limit,
                         None if room is None else round(room, 4))

    lines.append(line("position size", 0.0, lim["max_position_pct_nav"], pos_room))
    if sector:
        lines.append(line(f"sector concentration ({sector})", sec_used,
                          lim["max_sector_pct_nav"], sec_room))
    else:
        lines.append(LimitLine("sector concentration", "FAIL", None,
                               lim["max_sector_pct_nav"], None,
                               "sector unknown — concentration cannot be verified"))
    lines.append(line("gross exposure", exp["gross"], lim["max_gross_pct_nav"], gross_room))
    lines.append(line("net exposure", exp["net"], lim["max_net_pct_nav"], net_room))
    lines.append(LimitLine("aggregate/correlation risk", "NOT ASSESSED", None, None, None,
                           "no correlation data — a limit PASS is not 'safe for the book'"))
    return final, lines
