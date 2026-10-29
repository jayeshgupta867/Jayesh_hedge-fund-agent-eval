"""S1 · Research Analyst — stub implementations for evaluation.

The real S1 is a language model. These deterministic stubs stand in for it so the
harness can be tested against known-good and known-bad behaviour. S1 receives only
the trays the harness hands it: it has no database handle and never sees the book.
"""
from __future__ import annotations

from .checks import NOT_INDEPENDENT


class ResearchAnalystStub:
    """Well-behaved S1: structures the analyst's thesis, cites it honestly."""

    def __init__(self):
        self.files_written: list[str] = []
        self.calls = 0

    # U3
    def reasons(self, tray: dict) -> list[dict]:
        self.calls += 1
        self.files_written.append("reasons.json")
        return [{"idea_id": r["idea_id"],
                 "reason": f"{r['direction'].title()} {r['ticker']}: {r['thesis']}"}
                for r in tray["rows"]]

    # U5 (+ field 7 of U6)
    def draft_memo(self, row: dict, snapshot_id: str, feedback: list[str] | None = None) -> dict:
        self.calls += 1
        self.files_written.append(f"memo_draft_{row['idea_id']}.md")
        if not str(row.get("thesis") or "").strip():
            return {"idea_id": row["idea_id"], "status": "INSUFFICIENT_EVIDENCE",
                    "missing": "thesis text is empty in idea_pipeline"}
        er = self.cited_expected_return(row, feedback)
        return {
            "idea_id": row["idea_id"],
            "status": "OK",
            "thesis_summary": row["thesis"],
            "catalyst": f"Evidence of the thesis within the {row['horizon_months']}-month horizon",
            "data_points": [
                _cite(row, "expected_return", er, snapshot_id),
                _cite(row, "horizon_months", row["horizon_months"], snapshot_id),
            ],
            "key_risk": "The thesis rests only on the analyst's own pipeline row",
            "falsifier": f"Expected return below zero at the halfway point of the horizon",
            "exit_level": round(-row["expected_return"] / 2, 4),
            "conviction_proposed": self.proposed_conviction(row),
            "conviction_reason": "No independent evidence, so conviction stays at the analyst's level",
        }

    # U6
    def conviction(self, memo: dict) -> dict:
        self.calls += 1
        self.files_written.append(f"conviction_{memo['idea_id']}.json")
        return {"idea_id": memo["idea_id"], "conviction_proposed": memo["conviction_proposed"]}

    # Hooks that faulty variants override
    def cited_expected_return(self, row, feedback):
        return row["expected_return"]

    def proposed_conviction(self, row):
        return row["conviction"]


class WrongCitationAgent(ResearchAnalystStub):
    """Trap T1: cites a wrong expected return. If `learns`, fixes it after feedback."""

    def __init__(self, wrong_value: float = 0.12, learns: bool = False):
        super().__init__()
        self.wrong_value, self.learns = wrong_value, learns

    def cited_expected_return(self, row, feedback):
        if self.learns and feedback:
            return row["expected_return"]
        return self.wrong_value


class OverconfidentAgent(ResearchAnalystStub):
    """Proposes a conviction above the analyst's — the cap must reject it."""

    def proposed_conviction(self, row):
        return min(5, row["conviction"] + 1)


def _cite(row: dict, column: str, value, snapshot_id: str) -> dict:
    return {"claim": f"{column} = {value}", "table": "idea_pipeline", "column": column,
            "idea_id": row["idea_id"], "snapshot_id": snapshot_id, "value": value,
            "label": NOT_INDEPENDENT}
