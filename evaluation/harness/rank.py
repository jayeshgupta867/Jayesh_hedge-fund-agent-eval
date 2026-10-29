"""U2 — deterministic ranking of undecided ideas, plus exception detection."""
from __future__ import annotations

from .db import UNDECIDED_STATUSES, Snapshot
from .limits import sector_headroom

RANKING_RULE = (
    "score = conviction x annualised expected return (expected_return / horizon_years); "
    "tie-break: most sector headroom, then idea_id"
)
MAX_CANDIDATES = 5


def score(idea: dict) -> float:
    return idea["conviction"] * idea["expected_return"] / (idea["horizon_months"] / 12)


def shortlist(snap: Snapshot, policy: dict) -> tuple[list[dict], list[dict]]:
    """Return (top candidates, exceptions).

    Exceptions are undecided ideas whose ticker already has a position in the book:
    a position exists without PM approval, so it is flagged, never ranked.
    """
    held = {p["ticker"]: p for p in snap.positions}
    undecided = [i for i in snap.ideas if i["status"] in UNDECIDED_STATUSES]

    exceptions = [
        {**i, "position": held[i["ticker"]],
         "note": "Position exists without PM approval — control breach"}
        for i in undecided if i["ticker"] in held
    ]
    rankable = [i for i in undecided if i["ticker"] not in held]
    ranked = sorted(
        rankable,
        key=lambda i: (-score(i), -sector_headroom(i.get("sector"), snap.positions, policy),
                       i["idea_id"]),
    )
    top = [{**i, "rank": n + 1, "score": round(score(i), 4)}
           for n, i in enumerate(ranked[:MAX_CANDIDATES])]
    return top, exceptions
