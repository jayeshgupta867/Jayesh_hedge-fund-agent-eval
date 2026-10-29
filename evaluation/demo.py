"""Run the workflow once on the synthetic sample data and write the PM-facing outputs.

    python demo.py

Outputs go to runs/demo/: shortlist.md, one memo per selected idea, ticket.json, trace.md.
"""
import json
from datetime import datetime
from pathlib import Path

from harness.agent import ResearchAnalystStub
from harness.db import build_db, load_csv_dir
from harness.rank import RANKING_RULE
from harness.run import run_workflow

ROOT = Path(__file__).parent
OUT = ROOT / "runs" / "demo"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = build_db(OUT / "sample.db", load_csv_dir(ROOT / "data" / "sample"))
    res = run_workflow(db, ROOT / "policy" / "limit_policy.json", ResearchAnalystStub(),
                       last_close=datetime(2026, 10, 28, 22, 0),
                       clock=lambda: datetime(2026, 10, 29, 8, 0))

    (OUT / "shortlist.md").write_text(render_shortlist(res))
    for iid, memo in res.memos.items():
        (OUT / f"memo_{iid}.md").write_text(render_memo(iid, memo))
    (OUT / "ticket.json").write_text(json.dumps(
        {"status": res.status, "stop_reason": res.stop_reason, "note": res.note,
         "snapshot_id": res.snapshot_id, "ideas": res.ideas, "receipts": res.receipts},
        indent=2))
    (OUT / "trace.md").write_text(
        "# Trace\n\n" + " · ".join(f"{k}: {v}" for k, v in res.boundaries.items()) + "\n")
    print(f"Run status: {res.status}")
    print(" · ".join(f"{k}: {v}" for k, v in res.boundaries.items()))
    for iid, state in res.ideas.items():
        print(f"  {iid}: {state}")
    print(f"Outputs written to {OUT.relative_to(ROOT)}/")


def render_shortlist(res) -> str:
    lines = ["# Shortlist (gate 1)", ""]
    if res.exceptions:
        lines += ["## ⚠ Exceptions — positions exist without PM approval", ""]
        for e in res.exceptions:
            p = e["position"]
            lines.append(f"- **{e['idea_id']} {e['ticker']} {e['direction']}** — existing position "
                         f"{p['pct_nav']}% NAV, settlement: {p['settlement_status']}. {e['note']}.")
        lines.append("")
    lines += [f"Ranking rule: {RANKING_RULE}", "",
              "| Rank | Idea | Ticker | Dir | Score | Reason |", "|---|---|---|---|---|---|"]
    for c in res.shortlist:
        lines.append(f"| {c['rank']} | {c['idea_id']} | {c['ticker']} | {c['direction']} | "
                     f"{c['score']} | {res.reasons.get(c['idea_id'], '')} |")
    return "\n".join(lines) + "\n"


def render_memo(iid, m) -> str:
    if m.get("status") in ("STOPPED", "INSUFFICIENT_EVIDENCE"):
        return f"# {iid}: no memo — {m['status']}\n\n{m.get('missing') or m.get('reason')}\n"
    out = [f"# Trade memo {iid}", ""]
    out += [f"> **{f}**" for f in m["top_flags"]] + [""]
    out += [f"1. **Ticker / direction / date:** {m['1_ticker_direction_date']}",
            f"2. **Thesis:** {m['2_thesis_summary']}",
            f"3. **Catalyst:** {m['3_catalyst']}",
            "4. **Data points:**"]
    out += [f"   - {d['claim']} — {d['table']}.{d['column']} @ {d['snapshot_id']} "
            f"({d['label']})" for d in m["4_data_points"]]
    f8 = m["8_return_vol_liquidity"]
    out += [f"5. **Key risk:** {m['5_key_risk']}",
            f"6. **Falsifier / exit:** {m['6_falsifier_exit']}",
            f"7. **Proposed conviction:** {m['7_conviction_proposed']}",
            f"8. **Return / vol / liquidity:** {f8['expected_return']} / {f8['volatility']} / "
            f"{f8['adv_usd']} (owners: " + "; ".join(f"{k} – {v}" for k, v in f8['owners'].items()) + ")",
            f"9. **Size:** {m['9_size']}",
            "10. **Limit report:**"]
    out += [f"    - {l['name']}: **{l['result']}** (usage {l['usage']}, limit {l['limit']}, "
            f"headroom {l['headroom']}){' — ' + l['note'] if l['note'] else ''}"
            for l in m["10_limit_report"]]
    out += ["11. **PM decision:** ____________", "",
            f"_Policy {m['policy_version']} · snapshot {m['snapshot_id']}_"]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
