"""Fund dashboard: reads the state that GitHub Actions commits after every US close."""
from __future__ import annotations

import json
from pathlib import Path

import sys

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from fund.engine.report import pnl_by_book  # noqa: E402
from fund.engine.risk import book_of  # noqa: E402

STATE = ROOT / "fund" / "state"
POLICY = ROOT / "fund" / "policy"
REPO_URL = "https://github.com/jayeshgupta867/Jayesh_hedge-fund-agent-eval"

st.markdown("""
<style>
:root{--card:#16233a;--line:#26395a;--muted:#8fa3bf;--pos:#3fb68b;--neg:#e5534b;--warn:#d6a03a;}
.block-container{padding-top:2rem;max-width:1400px;}
.hdr h1{font-size:1.75rem;margin:0;} .hdr p{color:var(--muted);margin:.2rem 0 1rem 0;font-size:.95rem;}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;height:100%;}
.kpi .lbl{color:var(--muted);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;}
.kpi .val{font-size:1.55rem;font-weight:700;margin:.15rem 0;font-variant-numeric:tabular-nums;}
.kpi .sub{color:var(--muted);font-size:.78rem;}
.pos{color:var(--pos);} .neg{color:var(--neg);} .warn{color:var(--warn);}
.field{margin:.3rem 0;font-size:.92rem;} .field b{color:var(--muted);font-weight:600;}
.pm{background:#2a2412;border:1px solid var(--warn);border-radius:10px;padding:12px 16px;margin:.4rem 0 1rem 0;}
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load(mode: str) -> dict:
    d = STATE / mode
    out = {"nav": pd.DataFrame(), "positions": pd.DataFrame(), "trades": pd.DataFrame(), "days": {}, "pending": []}
    for name in ("nav", "positions", "trades"):
        f = d / f"{name}.csv"
        if f.exists() and f.stat().st_size:
            out[name] = pd.read_csv(f)
    for f in sorted((d / "days").glob("*.json")) if (d / "days").exists() else []:
        out["days"][f.stem] = json.loads(f.read_text())
    status = STATE / f"status_{mode}.json"
    out["status"] = json.loads(status.read_text()) if status.exists() else None
    pend = d / "pending.json"
    out["pending"] = json.loads(pend.read_text()) if pend.exists() else []
    return out


@st.cache_data(ttl=300)
def load_json(path: str):
    f = Path(path)
    return json.loads(f.read_text()) if f.exists() else None


def analyst_label(r: dict) -> str:
    used = r.get("analyst_used")
    if r["analyst"] != "groq":
        return "Template"
    if used == "model":
        return "AI model (Groq)"
    if used == "mixed":
        return "AI model + template"
    if used is None:  # v3 days: the configured analyst only
        failed = any("model unavailable" in m for m in r.get("analyst_log", []))
        return "Template (model unavailable)" if failed else "AI model (Groq)"
    return "Template (model unavailable)"


def kpi(col, label, value, sub="", tone=""):
    col.markdown(f'<div class="kpi"><div class="lbl">{label}</div><div class="val {tone}">{value}</div>'
                 f'<div class="sub">{sub}</div></div>', unsafe_allow_html=True)


def tone(x: float) -> str:
    return "pos" if x > 0 else "neg" if x < 0 else ""


# ------------------------------------------------------------------ sidebar
live_rows = len(load("live")["nav"])
with st.sidebar:
    mode = st.radio("Fund", ["Live", "Replay"], index=0 if live_rows else 1,
                    help="Live: paper trading since inception, updated after every US close. "
                         "Replay: the same engine run over past days.").lower()
    data = load(mode)
    s = data["status"]
    if s:
        (st.success if s.get("ok") else st.error)(f"Last run {s['run_at_utc']} UTC · {s['message']}")
    st.caption("Updated automatically by GitHub Actions after each US close (22:30 UTC, Mon–Fri). "
               "No laptop involved.")
    st.markdown(f"[Source code]({REPO_URL}) · [Run history]({REPO_URL}/actions)")
    mandate = load_json(str(POLICY / "mandate.json"))
    rt = load_json(str(STATE / "redteam.json"))
    if rt:
        (st.success if rt.get("ok") else st.error)(
            f"Safety tests {rt['run_at_utc']} UTC: {rt['attacks_blocked']}/{rt['attacks_total']} attacks blocked · "
            f"{rt['mutations_caught']}/{rt['mutations_total']} safeguards proven")
    if mandate:
        with st.expander("Mandate"):
            st.markdown(f"**Strategy:** {mandate['strategy']}  \n**Asset class:** {mandate['asset_class']}  \n"
                        f"**Execution:** {mandate['execution']}  \n**Sign-off:** {mandate['sign_off']}")

st.markdown(
    '<div class="hdr"><h1>Momentum Long/Short · Paper Fund</h1>'
    "<p>A screen picks the names · an AI analyst drafts and challenges each memo · code checks every number, "
    "the data and the book · standing rules sign systematic trades, the PM signs anything flagged · "
    "$1m of paper money, benchmark SPY</p></div>", unsafe_allow_html=True)

if mode == "live" and data["pending"]:
    items = data["pending"]
    st.markdown(f'<div class="pm"><b>⚑ {len(items)} trade(s) awaiting PM sign-off</b> · valid for the next run only '
                f'(22:30 UTC). Not booked unless approved.</div>', unsafe_allow_html=True)
    with st.expander("How to approve or reject", expanded=True):
        st.markdown(f"Edit [`fund/policy/pm_approvals.json`]({REPO_URL}/edit/main/fund/policy/pm_approvals.json) "
                    "on GitHub and paste the lines you want into the `approvals` list. "
                    "Change `approve` to `reject` to drop one. The next run re-checks limits, correlation, data and "
                    "price drift before booking, and never trades more than the size shown.")
        for it in items:
            st.markdown(f"**{it['ticker']} {it['direction']}** · {it['pct_nav']:.2f}% NAV at {it['price']:.2f} · "
                        + " · ".join(it["reasons"]))
            st.code(json.dumps({"idea_id": it["idea_id"], "token": it["token"], "decision": "approve"}), language="json")

nav = data["nav"]
if nav.empty:
    if mode == "live":
        st.info("The live fund starts on its first scheduled run after the US close. "
                "Switch to **Replay** in the sidebar to see the engine's track record over past days.")
    else:
        st.info("No replay yet. On GitHub: Actions → Fund run → Run workflow → mode **replay**.")
    st.stop()

# ------------------------------------------------------------------ KPIs
nav["date"] = pd.to_datetime(nav["date"])
last, first = nav.iloc[-1], nav.iloc[0]
capital = last["nav"] / last["fund_index"] * 100
fund_ret = last["fund_index"] / 100 - 1
spy_ret = last["spy_index"] / 100 - 1
peak = nav["nav"].cummax()
dd = nav["nav"] / peak - 1
pos = data["positions"]
pos_books = pos.apply(lambda r: book_of(r.to_dict()), axis=1) if not pos.empty else pd.Series(dtype=str)
n_long = int((pos_books == "LONG").sum())
n_short = int((pos_books == "SHORT").sum())
hedge_pct = float(last.get("hedge_pct")) if pd.notna(last.get("hedge_pct", float("nan"))) else 0.0
beta_net = last.get("beta_net_pct")

c = st.columns(4)
kpi(c[0], "Portfolio value", f"${last['nav']:,.0f}", f"{last['nav'] - capital:+,.0f} since {first['date']:%d %b %Y}",
    tone(fund_ret))
kpi(c[1], "Return vs SPY", f"{(fund_ret - spy_ret) * 100:+.2f} pp",
    f"fund {fund_ret:+.2%} · SPY {spy_ret:+.2%}", tone(fund_ret - spy_ret))
kpi(c[2], "Last day P&L", f"{last['daily_pnl']:+,.0f}", f"{last['date']:%a %d %b %Y}", tone(last["daily_pnl"]))
kpi(c[3], "Max drawdown", f"{dd.min():.2%}", f"current {dd.iloc[-1]:.2%}", "neg" if dd.min() < 0 else "")
st.write("")
c = st.columns(4)
kpi(c[0], "Cash", f"${last['cash']:,.0f}", f"{last['cash'] / last['nav']:.0%} of NAV")
kpi(c[1], "Gross / net exposure", f"{last['gross_pct']:.0f}% / {last['net_pct']:+.0f}%",
    f"beta-adjusted net {beta_net:+.1f}% · limits 150% / ±50%" if pd.notna(beta_net) else "limits 150% / ±50%")
kpi(c[2], "Positions", f"{n_long + n_short}",
    f"{n_long} long · {n_short} short" + (f" · hedge {hedge_pct:+.1f}% SPY" if hedge_pct else ""))
kpi(c[3], "Trades", f"{len(data['trades'])}", f"over {len(nav)} trading days")
st.write("")

# ------------------------------------------------------------------ charts
perf = nav.melt("date", ["fund_index", "spy_index"], var_name="series", value_name="index")
perf["series"] = perf["series"].map({"fund_index": "Fund", "spy_index": "SPY"})
line = alt.Chart(perf).mark_line(strokeWidth=2.2).encode(
    x=alt.X("date:T", title=None),
    y=alt.Y("index:Q", title="Growth of 100", scale=alt.Scale(zero=False)),
    color=alt.Color("series:N", scale=alt.Scale(domain=["Fund", "SPY"], range=["#4c8dff", "#8fa3bf"]),
                    legend=alt.Legend(orient="top-left", title=None)),
    tooltip=[alt.Tooltip("date:T"), "series:N", alt.Tooltip("index:Q", format=".2f")],
).properties(height=300)
st.altair_chart(line)
ddf = pd.DataFrame({"date": nav["date"], "drawdown": dd * 100})
st.altair_chart(alt.Chart(ddf).mark_area(color="#e5534b", opacity=0.35, line={"color": "#e5534b"}).encode(
    x=alt.X("date:T", title=None), y=alt.Y("drawdown:Q", title="Drawdown %"),
    tooltip=[alt.Tooltip("date:T"), alt.Tooltip("drawdown:Q", format=".2f")]).properties(height=130))

# ------------------------------------------------------------------ tabs
t_pos, t_books, t_trades, t_comm, t_safe, t_rules = st.tabs(
    ["Positions", "P&L by book", "Trades", "Committee", "Safety", "Rules & method"])

with t_pos:
    if pos.empty:
        st.caption("No open positions.")
    else:
        v = pos.copy()
        v["book"] = pos_books
        v["pnl"] = v["market_value"] - v["cost_basis"]
        v["pnl_pct"] = (v["market_value"] / v["cost_basis"] - 1) * 100 * v["direction"].map({"LONG": 1, "SHORT": -1})
        v["weight"] = v["market_value"] / last["nav"] * 100
        v = v.sort_values("weight", key=abs, ascending=False)
        st.dataframe(v[["book", "ticker", "sector", "entry_date", "entry_price", "last_price",
                        "market_value", "weight", "pnl", "pnl_pct"]], hide_index=True,
                     column_config={
                         "book": "Book", "ticker": "Ticker", "sector": "Sector", "entry_date": "Entry",
                         "entry_price": st.column_config.NumberColumn("Entry px", format="%.2f"),
                         "last_price": st.column_config.NumberColumn("Last px", format="%.2f"),
                         "market_value": st.column_config.NumberColumn("Market value", format="%.0f"),
                         "weight": st.column_config.NumberColumn("% NAV", format="%.2f"),
                         "pnl": st.column_config.NumberColumn("P&L $", format="%.0f"),
                         "pnl_pct": st.column_config.NumberColumn("P&L %", format="%.2f")})

with t_books:
    st.caption("The long book, the short book and the hedge follow different logic, so they are judged "
               "separately. P&L since inception = trade cash flows (incl. costs) + value still held. "
               "The three rows add up to the fund's total P&L.")
    books = pnl_by_book(pos, data["trades"])
    books["pnl_pct_capital"] = books["pnl"] / capital * 100
    st.dataframe(books, hide_index=True, column_config={
        "book": "Book", "pnl": st.column_config.NumberColumn("P&L $", format="%.0f"),
        "pnl_pct_capital": st.column_config.NumberColumn("% of capital", format="%.2f"),
        "open_positions": "Open", "trades": "Trades"})
    st.caption(f"Check: books sum to {books['pnl'].sum():+,.0f} · NAV change {last['nav'] - capital:+,.0f}")

with t_trades:
    tr = data["trades"]
    if tr.empty:
        st.caption("No trades yet.")
    else:
        st.dataframe(tr.iloc[::-1][["date", "ticker", "action", "shares", "price", "notional", "cost", "reason"]],
                     hide_index=True,
                     column_config={"notional": st.column_config.NumberColumn(format="%.0f"),
                                    "price": st.column_config.NumberColumn(format="%.2f")})

with t_comm:
    days = data["days"]
    pick = st.selectbox("Trading day", list(days)[::-1])
    r = days[pick]
    h = r.get("harness", {})
    a, b, c3 = st.columns(3)
    a.metric("Ideas from the screen", r["screen"]["ideas"])
    b.metric("Opened · closed", f"{len(r['executed'])} · {len(r['exits'])}")
    c3.metric("Analyst", analyst_label(r))
    for w in r.get("pm_alerts", []):
        st.warning(w)
    for w in r.get("warnings", []) + r.get("analyst_log", []):
        st.caption(f"⚠ {w}")
    if r.get("data_checks"):
        with st.expander("Data checks", expanded=any(c["result"] == "FAIL" for c in r["data_checks"])):
            st.dataframe(pd.DataFrame(r["data_checks"]), hide_index=True)
    if r.get("approvals"):
        st.markdown("**PM sign-offs resolved this day**")
        st.dataframe(pd.DataFrame(r["approvals"]), hide_index=True)
    if r.get("escalated"):
        st.markdown("**Sent to the PM** (not booked)")
        st.dataframe(pd.DataFrame([{**e, "reasons": " · ".join(e["reasons"])} for e in r["escalated"]]), hide_index=True)
    if r.get("hedge"):
        hg = r["hedge"]
        st.caption(f"Hedge book: long/short beta exposure {hg['book_beta_pct']:+.1f}% · SPY hedge "
                   f"{hg['before_pct']:+.1f}% → {hg['after_pct']:+.1f}% · beta-adjusted net {hg['beta_net_after_pct']:+.1f}%"
                   + (" · rebalanced" if hg.get("traded") else f" · {hg.get('note', '')}"))
    if not h:
        st.caption("No new ideas this day: every name that passed the screen is already held or vetoed.")
    if h.get("exceptions"):
        st.error(f"{len(h['exceptions'])} control exception(s): " + ", ".join(e["ticker"] for e in h["exceptions"]))
    if h.get("shortlist"):
        st.markdown("**Shortlist** (ranked by the script)")
        st.dataframe(pd.DataFrame(h["shortlist"])[["rank", "ticker", "direction", "sector", "conviction",
                                                    "momentum_12_1", "score", "reason"]], hide_index=True)
    if r["executed"] or r["skipped"] or r["exits"]:
        st.markdown("**Decisions** (PM standing rules)")
        rows = ([{"Ticker": t["ticker"], "Decision": t["action"], "Why": t["reason"]} for t in r["exits"]] +
                [{"Ticker": t["ticker"], "Decision": t["action"], "Why": "memo passed every check and rule"}
                 for t in r["executed"]] +
                [{"Ticker": s["ticker"], "Decision": "not traded", "Why": s["reason"]} for s in r["skipped"]])
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    for iid, m in (h.get("memos") or {}).items():
        state = h["ideas"].get(iid, "")
        with st.expander(f"Memo {iid} · {state}"):
            if state != "MEMO_READY":
                st.write(m.get("reason") or m.get("missing"))
                for f in m.get("failures") or []:
                    st.code(f, language=None)
                continue
            for f in m["top_flags"]:
                st.caption(f"⚑ {f}")
            for label, key in [("Thesis", "2_thesis_summary"), ("Catalyst", "3_catalyst"), ("Key risk", "5_key_risk"),
                               ("Falsifier / exit", "6_falsifier_exit"), ("Conviction", "7_conviction_proposed"),
                               ("Size (harness)", "9_size")]:
                st.markdown(f"<div class='field'><b>{label}:</b> {m[key]}</div>", unsafe_allow_html=True)
            st.caption(" · ".join(f"{d['column']}={d['value']}" for d in m["4_data_points"]))
            dec = (r.get("decisions") or {}).get(iid)
            if dec and dec.get("checks"):
                st.markdown("<div class='field'><b>Book checks (v4):</b></div>", unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(dec["checks"])[["check", "result", "note"]], hide_index=True)
    if h.get("boundaries"):
        st.caption("Boundaries: " + " · ".join(f"{k}: {v}" for k, v in h["boundaries"].items()))

with t_safe:
    st.markdown("""**Safeguard stack.** The AI drafts and questions; it never sizes, approves or books.
1. **Data gate:** no intraday prices, no stale feed, unconfirmed jumps and frozen prices quarantined, benchmark glitch stops the day.
2. **Harness:** every cited number must match the data, conviction capped, agent cannot write size or PM fields, read-only database.
3. **Book checks:** limits, 3% of ADV, correlation with the book, crowded shorts, analyst challenge (escalate only).
4. **Sign-off:** systematic trades by standing rules; flagged trades wait for a PM approval bound to the exact trade, valid one run, ignored if written by the automation.
5. **Fail-safes:** any failing test or untested safeguard means no trading that day; the run may only change `fund/state`; git is the audit trail.""")
    if not rt:
        st.caption("No red-team report yet: it is written by the next GitHub Actions run.")
    else:
        a1, a2 = st.columns(2)
        a1.metric("Attacks blocked", f"{rt['attacks_blocked']}/{rt['attacks_total']}")
        a2.metric("Safeguards proven by mutation", f"{rt['mutations_caught']}/{rt['mutations_total']}")
        st.dataframe(pd.DataFrame(rt["attacks"])[["id", "title", "category", "attack", "expected", "result"]],
                     hide_index=True)
        if rt.get("mutations"):
            st.markdown("**Mutation check:** each safeguard is switched off in turn; the attacks it stops must then "
                        "succeed (their tests fail). A safeguard whose tests still passed would not really be tested.")
            st.dataframe(pd.DataFrame(rt["mutations"])[["safeguard", "tests", "caught"]], hide_index=True)

with t_rules:
    from fund.engine.policy import load_limit_policy, load_rules
    rules = load_rules(POLICY / "standing_rules.json")
    limits = load_limit_policy(POLICY / "limit_policy.json")
    veto = json.loads((POLICY / "pm_overrides.json").read_text())
    st.markdown(f"""
**How a trade happens**
1. **Data gate (code):** only closed sessions, fresh data, no unconfirmed jumps or frozen prices.
2. **Screen (code):** about 100 large-cap US stocks ranked on 12-1 momentum. Longs: top names above their 200-day average. Shorts: weakest names below it.
3. **Harness (code, 18 tests):** ranks the top 5, checks every memo, sizes by volatility, checks limits.
4. **S1 analyst (AI model in live mode):** writes each memo and cites the screen's numbers, then **challenges its input** (for example, a trend that comes from one day). It can escalate, never approve.
5. **Book checks (code):** at most {limits['liquidity']['max_trade_pct_adv']}% of ADV; correlation with the book above {limits['correlation']['halve_above']} halves the size, above {limits['correlation']['reject_above']} rejects it; shorts with more than {rules['short_book']['max_short_interest_pct_float']}% of float sold short are not added.
6. **Sign-off:** standing rules sign trades inside the mandate (conviction ≥ {rules['min_conviction']}, at most {rules['max_new_trades_per_day']} new trades a day). Anything flagged waits for the PM.
7. **Three books:** long stop {rules['stop_loss_pct']}%, short stop {rules['stop_loss_short_pct']}% (losses on a short are unbounded), max holding {rules['max_holding_days']} trading days or the signal fades. The SPY hedge keeps beta-adjusted net near {rules['hedge']['target_net_beta_pct']}% ({'on' if rules['hedge']['enabled'] else 'off'}).
8. **PM veto:** edit `fund/policy/pm_overrides.json` on GitHub. Vetoed now: {', '.join(veto['veto_tickers']) or 'none'}.

**Limits** (version {limits['version']}): position {limits['limits']['max_position_pct_nav']}% · sector {limits['limits']['max_sector_pct_nav']}% · gross {limits['limits']['max_gross_pct_nav']}% · net ±{limits['limits']['max_net_pct_nav']}% of NAV.

**Not assessed (declared, not faked):** closing-auction share (no auction volume data), order-book depth L2/L3 and options-market liquidity, point-in-time short interest in the replay.

**Incident log**
- *2 Nov 2026:* the first live run was started during US market hours, so five positions were booked at intraday prices. Marks since then use official closes, which overstates P&L on those five positions by about $2.7k (0.27% of NAV). The history is left as it was (git is the audit trail). v4 never books an open session (red-team test R17).
- *2–5 Nov 2026:* every Groq call failed (HTTP error), so the template wrote all memos; v3 still labelled them "AI model". v4 reports what actually wrote each memo and logs the HTTP status.
- *2–5 Nov 2026:* day 1 bought five highly correlated chip/software longs; three hit their stops on 5 Nov and the five lost about $14.7k together. v4 checks correlation with the book (red-team test R21).

**Honest caveats**
- Paper trading: fills at the daily close with {rules['transaction_cost_bps']} bps plus a square-root impact estimate; no borrow cost on shorts.
- Replay uses today's large-cap list (survivorship bias) and the template analyst, because an AI model trained on later data could leak hindsight into past decisions.
- Momentum is a well-known factor; this demonstrates a controlled process, not a proprietary edge.
""")
