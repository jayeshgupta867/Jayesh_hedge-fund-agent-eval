"""PM sign-off for flagged trades (v4, Gianluca: systematic trades inside the model's
parameters are signed automatically; anything outside them is signed by hand).

Flow
1. A trade that passes every check but carries a flag (analyst challenge, crowding or
   correlation not verifiable) is NOT booked. It is queued in fund/state/live/pending.json
   with a token that binds the exact trade: idea, day, side, size and price.
2. The PM approves by adding {"token", "idea_id", "decision": "approve"} to
   fund/policy/pm_approvals.json on GitHub (a human commit).
3. The next run re-checks everything at today's prices and books the trade only if the
   token matches, the approval has not expired, the price has not moved materially, the
   ticker is not vetoed, and limits and correlation still pass. The approved size is a
   ceiling: the engine may trade less, never more.

The automation can never approve its own trades: approvals are ignored if the file's last
commit was made by the bot, and the workflow fails if the engine changes anything outside
fund/state.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

BOT_AUTHORS = {"fund-bot", "github-actions[bot]"}


def token(item: dict) -> str:
    raw = (f"{item['idea_id']}|{item['date_queued']}|{item['direction']}|"
           f"{float(item['pct_nav']):.4f}|{float(item['price']):.4f}")
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def token_matches(item: dict, approval: dict) -> bool:
    return approval.get("token") == token(item) and approval.get("idea_id") == item["idea_id"]


def last_author(path: Path) -> str | None:
    """Author of the last commit that touched `path`, or None if git cannot tell."""
    path = Path(path).resolve()
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%an", "--", path.name],
                             cwd=path.parent, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    name = out.stdout.strip()
    return name if out.returncode == 0 and name else None


def load_pm_approvals(path: Path, author_fn=None) -> dict:
    """Return {"items": [...], "trusted": bool, "warning": str | None}. Fails closed."""
    path = Path(path)
    if not path.exists():
        return {"items": [], "trusted": True, "warning": None}
    try:
        data = json.loads(path.read_text())
        items = data.get("approvals", [])
        if not isinstance(items, list) or not all(isinstance(a, dict) for a in items):
            raise ValueError("'approvals' must be a list of objects")
    except (OSError, ValueError, AttributeError) as exc:
        return {"items": [], "trusted": False, "warning": f"approvals file unreadable, none applied ({exc})"}
    if not items:
        return {"items": [], "trusted": True, "warning": None}
    author = (author_fn or last_author)(path)
    if author is None:
        trusted = os.environ.get("FUND_TRUST_LOCAL_APPROVALS") == "1"
        warning = None if trusted else "approvals ignored: the file's author could not be verified with git"
        return {"items": items, "trusted": trusted, "warning": warning}
    if author.lower() in {b.lower() for b in BOT_AUTHORS}:
        return {"items": items, "trusted": False,
                "warning": f"approvals ignored: last change to the file was made by the automation ({author})"}
    return {"items": items, "trusted": True, "warning": None}


def is_expired(item: dict, date: str, trading_dates: list[str], valid_days: int) -> bool:
    """An approval is valid only for the next `valid_days` trading day(s) after queueing."""
    later = [d for d in trading_dates if d > item["date_queued"]]
    if not later:
        return False
    deadline = later[min(valid_days, len(later)) - 1]
    return date > deadline


def find_approval(item: dict, approvals: list[dict]) -> dict | None:
    return next((a for a in approvals if a.get("idea_id") == item["idea_id"]), None)
