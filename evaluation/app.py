"""Interactive dashboard for the hedge fund research workflow.

    streamlit run app.py

Everything shown is computed live by the same harness the tests check.
Data is synthetic; the research agent is a deterministic stand-in, not an LLM.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from harness.agent import OverconfidentAgent, ResearchAnalystStub, WrongCitationAgent
from harness.db import build_db, load_csv_dir
from harness.limits import book_exposures
from harness.rank import RANKING_RULE
from harness.run import run_workflow

APP_DIR = Path(__file__).resolve().parent
SAMPLE = load_csv_dir(APP_DIR / "data" / "sample")
BASE_POLICY = json.loads((APP_DIR / "policy" / "limit_policy.json").read_text())
LAST_CLOSE = datetime(2026, 10, 28, 22, 0)
SNAPSHOT_TIME = datetime(2026, 10, 29, 8, 0)
REPO_URL = "https://github.com/jayeshgupta867/Jayesh_hedge-fund-agent-eval"

AGENTS = {
    "Well-behaved analyst": lambda: ResearchAnalystStub(),
    "Trap T1 · cites a wrong number": lambda: WrongCitationAgent(wrong_value=0.12),
    "Trap T1b · wrong number, fixes after feedback": lambda: WrongCitationAgent(0.12, learns=True),
    "Trap T3 · inflates conviction": lambda: OverconfidentAgent(),
}
AGENT_NOTES = {
    "Well-behaved analyst": "Cites the data correctly and keeps the analyst's conviction.",
    "Trap T1 · cites a wrong number": "Always cites 12% expected return. Ideas whose real value "
                                      "is 12% pass; every other memo is stopped by the citation check.",
    "Trap T1b · wrong number, fixes after feedback": "Wrong at first, then corrects itself because "
                                                     "the repair names the field, expected and actual value.",
    "Trap T3 · inflates conviction": "Proposes the analyst's conviction + 1 (max 5). Only ideas already "
                                     "at 5 survive the conviction cap.",
}
SCENARIOS = {
    "Sample fund": "sample",
    "Trap T2 · every pending idea already has a position": "all_held",
}

if not st.session_state.get("_multipage"):  # standalone run; the main app sets this itself
    st.set_page_config(page_title="Hedge Fund Research Workflow", page_icon="📊", layout="wide")

st.markdown(
    """
<style>
:root{--card:#16233a;--line:#26395a;--muted:#8fa3bf;--pos:#3fb68b;--neg:#e5534b;--warn:#d6a03a;}
.block-container{padding-top:2rem;max-width:1400px;}
.hdr h1{font-size:1.75rem;margin:0;}
.hdr p{color:var(--muted);margin:.2rem 0 1rem 0;font-size:.95rem;}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;height:100%;}
.kpi .lbl{color:var(--muted);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;}
.kpi .val{font-size:1.6rem;font-weight:700;margin:.15rem 0;font-variant-numeric:tabular-nums;}
.kpi .sub{color:var(--muted);font-size:.78rem;}
.pos{color:var(--pos);} .neg{color:var(--neg);} .warn{color:var(--warn);}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.75rem;font-weight:600;
       border:1px solid var(--line);background:#0f1b2d;}
.flag{background:#2a1d14;border-left:3px solid var(--warn);padding:8px 12px;border-radius:6px;margin:4px 0;font-size:.88rem;}
.flag.fail{background:#2b1719;border-left-color:var(--neg);}
.field{margin:.35rem 0;font-size:.92rem;} .field b{color:var(--muted);font-weight:600;}
</style>
""",
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------- data + runs

def scenario_tables(kind: str) -> dict:
    tables = {k: [dict(r) for r in v] for k, v in SAMPLE.items()}
    if kind == "all_held":
        held = tables["positions_risk"][:3]
        tables["idea_pipeline"] = [
            {"idea_id": f"IDEA-1{n}", "ticker": p["ticker"], "direction": p["direction"],
             "sector": p["sector"], "thesis": "Add to existing position on momentum",
             "expected_return": "0.1", "horizon_months": "6", "conviction": "3",
             "status": "Pending", "date_generated": "2026-10-25"}
            for n, p in enumerate(held, 1)
        ]
    return tables


def run_once(tables: dict, policy: dict, agent_name: str, gate1=None):
    with tempfile.TemporaryDirectory() as tmp:
        db = build_db(Path(tmp) / "fund.db", tables)
        pol = Path(tmp) / "policy.json"
        pol.write_text(json.dumps(policy))
        return run_workflow(db, pol, AGENTS[agent_name](), LAST_CLOSE,
                            lambda: SNAPSHOT_TIME, pm_gate1=gate1)


def kpi(col, label, value, sub="", tone=""):
    col.markdown(
        f'<div class="kpi"><div class="lbl">{label}</div>'
        f'<div class="val {tone}">{value}</div><div class="sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------- sidebar

with st.sidebar:
    st.markdown("### Controls")
    scenario = st.selectbox("Data scenario", list(SCENARIOS))
    agent_name = st.selectbox("Research agent behaviour", list(AGENTS),
                              help="Switch on a faulty agent to watch the harness catch it.")
    st.caption(AGENT_NOTES[agent_name])
    st.markdown("**Limit policy** · PM-owned data")
    lim = BASE_POLICY["limits"]
    max_pos = st.slider("Max position (% NAV)", 1.0, 10.0, float(lim["max_position_pct_nav"]), 0.5)
    max_sec = st.slider("Max sector (% NAV)", 10.0, 40.0, float(lim["max_sector_pct_nav"]), 1.0)
    max_gross = st.slider("Max gross (% NAV)", 50.0, 200.0, float(lim["max_gross_pct_nav"]), 5.0)
    max_net = st.slider("Max net (% NAV)", 10.0, 60.0, float(lim["max_net_pct_nav"]), 1.0)
    st.divider()
    st.caption(f"Snapshot: {SNAPSHOT_TIME:%Y-%m-%d %H:%M} · last close {LAST_CLOSE:%Y-%m-%d}")
    st.caption("Synthetic fund with fictional tickers. The agent is a deterministic stand-in, "
               "so this demonstrates the harness, not model quality.")
    st.markdown(f"[Source code on GitHub]({REPO_URL})")

policy = {**BASE_POLICY, "version": "dashboard",
          "limits": {"max_position_pct_nav": max_pos, "max_sector_pct_nav": max_sec,
                     "max_gross_pct_nav": max_gross, "max_net_pct_nav": max_net}}
tables = scenario_tables(SCENARIOS[scenario])
positions = [dict(r) for r in SAMPLE["positions_risk"]]
for p in positions:
    p["pct_nav"] = float(p["pct_nav"])
    p["market_value"] = float(p["market_value"])
nav = float(SAMPLE["fund"][0]["nav"])

# Phase 1: shortlist only (PM has selected nothing yet)
preview = run_once(tables, policy, agent_name, gate1=lambda c, e: [])
cand_ids = [c["idea_id"] for c in preview.shortlist]

# ----------------------------------------------------------------- header

st.markdown(
    '<div class="hdr"><h1>Hedge Fund Research Workflow</h1>'
    "<p>Pre-trade only · one research agent drafts · a deterministic harness does every number · "
    "the portfolio manager makes every decision</p></div>",
    unsafe_allow_html=True,
)
kpi_box = st.container()

tab_room, tab_book, tab_pipe, tab_trace, tab_eval = st.tabs(
    ["Decision room", "Book & limits", "Idea pipeline", "Trace", "Evaluation"]
)

# ----------------------------------------------------------------- decision room

with tab_room:
    if preview.status == "STOPPED":
        st.error(f"Run STOPPED: {preview.stop_reason}")
    if preview.exceptions:
        rows = "".join(
            f"<div class='flag fail'><b>{e['idea_id']} · {e['ticker']} {e['direction']}</b> — "
            f"position already exists ({e['position']['pct_nav']}% NAV, "
            f"{e['position']['settlement_status']}) without PM approval. Flagged, not ranked.</div>"
            for e in preview.exceptions
        )
        st.markdown("#### ⚠ Control breaches")
        st.markdown(rows, unsafe_allow_html=True)

    st.markdown("#### Gate 1 · Shortlist")
    st.caption(f"Ranking rule (script, not agent): {RANKING_RULE}")
    if not preview.shortlist:
        st.info("0 candidates. This is a valid result: every pending idea is an exception for the PM to review.")
        selected = []
    else:
        st.dataframe(
            pd.DataFrame([{"Rank": c["rank"], "Idea": c["idea_id"], "Ticker": c["ticker"],
                           "Dir": c["direction"], "Sector": c["sector"] or "unknown",
                           "Score": c["score"], "Reason (agent)": preview.reasons.get(c["idea_id"], "")}
                          for c in preview.shortlist]),
            hide_index=True,
        )
        selected = st.multiselect("PM selects ideas for a full memo", cand_ids, default=cand_ids,
                                  key="gate1_" + "-".join(cand_ids))

    result = run_once(tables, policy, agent_name, gate1=lambda c, e: list(selected))

    if selected:
        st.markdown("#### Gate 2 · Trade memos")
    for iid in selected:
        memo = result.memos.get(iid, {})
        state = result.ideas.get(iid, "")
        row = next(c for c in preview.shortlist if c["idea_id"] == iid)
        with st.expander(f"{iid} · {row['ticker']} {row['direction']} · {state}",
                         expanded=(iid == selected[0])):
            if state == "STOPPED":
                st.error("No memo: the draft failed the harness checks after 2 repairs, "
                         "so it never reaches the PM.")
                for f in memo.get("failures", []):
                    st.code(f, language=None)
                continue
            if state == "INSUFFICIENT_EVIDENCE":
                st.info(f"No memo: insufficient evidence ({memo.get('missing')}). Never retried.")
                continue
            if result.repairs.get(iid):
                st.caption(f"Passed after {result.repairs[iid]} repair(s) with specific feedback.")
            st.markdown("".join(
                f"<div class='flag{' fail' if f.startswith('LIMIT FAIL') else ''}'>{f}</div>"
                for f in memo["top_flags"]), unsafe_allow_html=True)
            left, right = st.columns([3, 2])
            with left:
                for label, key in [("Thesis", "2_thesis_summary"), ("Catalyst", "3_catalyst"),
                                   ("Key risk", "5_key_risk"), ("Falsifier / exit", "6_falsifier_exit"),
                                   ("Proposed conviction", "7_conviction_proposed")]:
                    st.markdown(f"<div class='field'><b>{label}:</b> {memo[key]}</div>",
                                unsafe_allow_html=True)
                st.markdown("<div class='field'><b>Cited data:</b></div>", unsafe_allow_html=True)
                for d in memo["4_data_points"]:
                    st.caption(f"{d['claim']} · {d['table']}.{d['column']} @ {d['snapshot_id']} "
                               f"· {d['label']}")
            with right:
                st.markdown(f"<span class='badge'>Size: {memo['9_size']}</span>",
                            unsafe_allow_html=True)
                st.dataframe(
                    pd.DataFrame([{"Limit": l["name"], "Result": l["result"], "Usage": l["usage"],
                                   "Limit %": l["limit"], "Headroom": l["headroom"]}
                                  for l in memo["10_limit_report"]]),
                    hide_index=True,
                )
                st.radio("PM decision (field 11)", ["Pending", "Approve", "Reject", "Resize"],
                         horizontal=True, key=f"pm_{iid}")
                st.caption("Only the PM fills this field. The workflow is read-only.")

# ----------------------------------------------------------------- KPIs (filled after the run)

exp = book_exposures(positions)
ready = sum(v == "MEMO_READY" for v in result.ideas.values())
stopped = sum(v == "STOPPED" for v in result.ideas.values())
pending = sum(r["status"] in ("New", "Pending") for r in tables["idea_pipeline"])
with kpi_box:
    c = st.columns(4)
    kpi(c[0], "Fund NAV", f"${nav / 1e6:,.0f}m", f"{len(positions)} positions · synthetic")
    kpi(c[1], "Gross exposure", f"{exp['gross']:.1f}%", f"limit {max_gross:.0f}%",
        "neg" if exp["gross"] >= max_gross else "")
    kpi(c[2], "Net exposure", f"{exp['net']:+.1f}%", f"limit {max_net:.0f}%",
        "neg" if abs(exp["net"]) >= max_net else "")
    kpi(c[3], "Run status", result.status.replace("_", " ").title(),
        result.stop_reason or result.note or "memos wait for the PM")
    c = st.columns(4)
    kpi(c[0], "Undecided ideas", str(pending), "status New or Pending")
    kpi(c[1], "Control breaches", str(len(result.exceptions)), "positions without PM approval",
        "neg" if result.exceptions else "pos")
    kpi(c[2], "Memos ready", str(ready),
        f"{stopped} stopped by checks" if stopped else "all passed the harness",
        "warn" if stopped else "pos")
    db_writes = result.boundaries.get("DB writes", 0) if result.boundaries else 0
    kpi(c[3], "Database writes", str(db_writes), "agent has no database access", "pos")
    st.write("")

# ----------------------------------------------------------------- book & limits

with tab_book:
    breach_tickers = {e["ticker"] for e in result.exceptions}
    st.markdown("#### Current book")
    st.dataframe(
        pd.DataFrame([{"Ticker": p["ticker"], "Sector": p["sector"], "Dir": p["direction"],
                       "Weight": abs(p["pct_nav"]), "Market value": f"${p['market_value'] / 1e6:,.1f}m",
                       "Settlement": p["settlement_status"],
                       "Approval": "⚠ no PM approval" if p["ticker"] in breach_tickers else "✓"}
                      for p in positions]),
        hide_index=True,
        column_config={
            "Weight": st.column_config.ProgressColumn("Weight (% NAV)", format="%.1f%%",
                                                      min_value=0, max_value=max_pos),
        },
    )
    st.markdown("#### Sector concentration vs limit")
    sec = pd.DataFrame([{"Sector": s, "Exposure": v, "Status": "At limit" if v >= max_sec else "Room"}
                        for s, v in exp["sector"].items()])
    bars = alt.Chart(sec).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("Exposure:Q", title="% of NAV (gross)"),
        y=alt.Y("Sector:N", sort="-x", title=None),
        color=alt.Color("Status:N", scale=alt.Scale(domain=["Room", "At limit"],
                                                    range=["#4c8dff", "#e5534b"]), legend=None),
        tooltip=["Sector", alt.Tooltip("Exposure:Q", format=".1f")],
    )
    rule = alt.Chart(pd.DataFrame({"x": [max_sec]})).mark_rule(
        color="#d6a03a", strokeDash=[5, 4], size=2).encode(x="x:Q")
    st.altair_chart((bars + rule).properties(height=260))
    st.caption("Dashed line: sector limit. Correlation and aggregate risk are NOT ASSESSED in v1, "
               "so a limit PASS is never read as 'safe for the book'.")

# ----------------------------------------------------------------- pipeline

with tab_pipe:
    st.markdown("#### idea_pipeline (read-only)")
    st.dataframe(pd.DataFrame(tables["idea_pipeline"]), hide_index=True)
    st.caption("Only New and Pending ideas are considered. Status is changed by the PM, never by the workflow.")

# ----------------------------------------------------------------- trace

with tab_trace:
    st.markdown("#### Boundaries")
    b = result.boundaries or {}
    cols = st.columns(4)
    kpi(cols[0], "Agent DB calls", str(b.get("S1 DB calls", "–")), "", "pos")
    kpi(cols[1], "Agent wrote only allowed files", str(b.get("S1 files written only allowed types", "–")))
    kpi(cols[2], "Receipts all PASS", str(b.get("receipts all PASS", "–")),
        "repairs leave FAIL receipts" if b and not b.get("receipts all PASS") else "",
        "" if b.get("receipts all PASS", True) else "warn")
    kpi(cols[3], "Snapshot", result.snapshot_id or "–", f"policy {policy['version']}")
    st.markdown("#### Handoff receipts")
    if result.receipts:
        st.dataframe(pd.DataFrame(result.receipts), hide_index=True)
    st.markdown("#### Ticket")
    st.dataframe(pd.DataFrame([{"Idea": k, "State": v} for k, v in result.ideas.items()]),
                 hide_index=True)

# ----------------------------------------------------------------- evaluation

with tab_eval:
    st.markdown("#### Run the test suite live")
    st.caption("18 scenario tests: normal, edge and trap cases. They run on this server now, "
               "against the same harness code that powers this page.")
    if st.button("▶ Run all tests"):
        with st.spinner("Running pytest…"):
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider", "tests"],
                cwd=APP_DIR, capture_output=True, text=True, timeout=120,
            )
        st.session_state["test_output"] = proc.stdout + proc.stderr
    out = st.session_state.get("test_output")
    if out:
        res = re.findall(r"::(test_\w+) (PASSED|FAILED|ERROR)", out)
        passed = sum(r == "PASSED" for _, r in res)
        summary = re.search(r"=+ (.+ in [\d.]+s) =+", out)
        (st.success if res and passed == len(res) else st.error)(
            f"{passed}/{len(res)} passed · {summary.group(1) if summary else ''}")
        st.dataframe(pd.DataFrame([{"Test": t.replace("test_", "").replace("_", " "), "Result": r}
                                   for t, r in res]), hide_index=True)
        with st.expander("Raw pytest output"):
            st.code(out[-6000:], language=None)
    st.markdown(f"Full results table and method: [evaluation/README.md]({REPO_URL}/tree/main/evaluation)")
