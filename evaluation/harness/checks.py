"""Deterministic checks the harness runs on everything S1 (the agent) produces.

S1 never checks its own work. Every failure names the check, the field, and
expected vs actual, so a repair attempt gets specific feedback, never "try again".
"""
from __future__ import annotations

from dataclasses import dataclass

NOT_INDEPENDENT = "source: analyst's pipeline row – not independent evidence"
MEMO_FIELDS = ["idea_id", "status", "thesis_summary", "catalyst", "data_points",
               "key_risk", "falsifier", "exit_level", "conviction_proposed",
               "conviction_reason"]
# Fields 1 and 8–11 belong to the harness or the PM; S1 must never write them.
FORBIDDEN_FOR_S1 = {"ticker", "direction", "expected_return_field", "volatility",
                    "liquidity", "size", "limit_report", "pm_decision", "final_conviction"}


@dataclass
class Failure:
    check: str
    field: str
    expected: object
    actual: object

    def __str__(self):
        return f"{self.check} [{self.field}]: expected {self.expected!r}, got {self.actual!r}"


class TrayMismatch(Exception):
    pass


def validate_tray(tray: dict, ticket_snapshot_id: str, expected_ids: set[str] | None = None):
    """Pre-copy validation before S1 sees anything (the acceptance step)."""
    if tray.get("snapshot_id") != ticket_snapshot_id:
        raise TrayMismatch(
            f"tray snapshot {tray.get('snapshot_id')} != ticket snapshot {ticket_snapshot_id}"
        )
    ids = {r["idea_id"] for r in tray["rows"]}
    if expected_ids is not None and ids != expected_ids:
        raise TrayMismatch(f"tray ideas {sorted(ids)} != expected {sorted(expected_ids)}")


def check_reasons(reasons: list[dict], candidate_ids: set[str]) -> list[Failure]:
    got = {r.get("idea_id") for r in reasons}
    fails = []
    if got != candidate_ids:
        fails.append(Failure("reasons cover candidates", "idea_id", sorted(candidate_ids), sorted(got)))
    for r in reasons:
        if not str(r.get("reason", "")).strip():
            fails.append(Failure("reason present", r.get("idea_id"), "non-empty", r.get("reason")))
    return fails


def check_memo(memo: dict, conviction_file: dict | None, row: dict,
               snapshot_id: str) -> list[Failure]:
    fails: list[Failure] = []

    leaked = FORBIDDEN_FOR_S1 & set(memo)
    if leaked:
        fails.append(Failure("S1 wrote harness/PM fields", "fields 1, 8–11", "none", sorted(leaked)))

    if memo.get("status") == "INSUFFICIENT_EVIDENCE":
        if not memo.get("missing"):
            fails.append(Failure("escalation names missing data", "missing", "non-empty", None))
        if conviction_file is not None:
            fails.append(Failure("no conviction on escalation", "conviction.json", None, conviction_file))
        return fails

    for f in MEMO_FIELDS:
        if f not in memo or memo[f] in (None, "", []):
            fails.append(Failure("required field", f, "present", memo.get(f)))

    for i, dp in enumerate(memo.get("data_points") or []):
        where = f"field 4, data point {i + 1}"
        if dp.get("label") != NOT_INDEPENDENT:
            fails.append(Failure("citation label", where, NOT_INDEPENDENT, dp.get("label")))
        if dp.get("snapshot_id") != snapshot_id:
            fails.append(Failure("citation snapshot", where, snapshot_id, dp.get("snapshot_id")))
        col = dp.get("column")
        if dp.get("table") != "idea_pipeline" or col not in row:
            fails.append(Failure("citation source exists", where, "idea_pipeline.<column>",
                                 f"{dp.get('table')}.{col}"))
        elif not _same(dp.get("value"), row[col]):
            fails.append(Failure("citation value matches snapshot", where, row[col], dp.get("value")))

    if not str(memo.get("falsifier", "")).strip():
        fails.append(Failure("falsifier present", "field 6", "non-empty", memo.get("falsifier")))
    if not isinstance(memo.get("exit_level"), (int, float)) or isinstance(memo.get("exit_level"), bool):
        fails.append(Failure("exit level is a number", "field 6", "number", memo.get("exit_level")))

    conv = memo.get("conviction_proposed")
    if not isinstance(conv, int) or not 1 <= conv <= 5:
        fails.append(Failure("conviction scale", "field 7", "integer 1–5", conv))
    elif conv > row["conviction"]:
        fails.append(Failure("conviction cap", "field 7", f"<= {row['conviction']}", conv))
    if conviction_file is None or conviction_file.get("conviction_proposed") != conv:
        fails.append(Failure("conviction file matches field 7", "conviction.json", conv,
                             None if conviction_file is None else conviction_file.get("conviction_proposed")))
    elif conviction_file.get("idea_id") != row["idea_id"]:
        fails.append(Failure("conviction file idea_id", "conviction.json", row["idea_id"],
                             conviction_file.get("idea_id")))
    return fails


def _same(a, b, tol=1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b
