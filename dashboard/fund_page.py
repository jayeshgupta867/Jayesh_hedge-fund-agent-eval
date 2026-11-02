"""Fund dashboard: reads the state that GitHub Actions commits after every US close."""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
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
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load(mode: str) -> dict:
    d = STATE / mode
    out = {"nav": pd.DataFrame(), "positions": pd.DataFrame(), "trades": pd.DataFrame(), "days": {}}
    for name in ("nav", "positions", "trades"):
        f = d / f"{name}.csv"
        if f.exists() and f.stat().st_size:
            out[name] = pd.read_csv(f)
    for f in sorted((d / "days").glob("*.json")) if (d / "days").exists() else []:
        out["days"][f.stem] = json.loads(f.read_text())
    status = STATE / f"status_{mode}.json"
    out["status"] = json.loads(status.read_text()) if status.exists() else None
    return out


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

st.markdown(
    '<div class="hdr"><h1>Momentum Long/Short · Paper Fund</h1>'
    "<p>A screen picks the names · an AI analyst drafts each memo · the harness checks every number · "
    "the PM's standing rules decide · $1m of paper money, benchmark SPY</p></div>", unsafe_allow_html=True)

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
n_long = int((pos["direction"] == "LONG").sum()) if not pos.empty else 0
n_short = int((pos["direction"] == "SHORT").sum()) if not pos.empty else 0

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
kpi(c[1], "Gross / net exposure", f"{last['gross_pct']:.0f}% / {last['net_pct']:+.0f}%", "limits 150% / ±50%")
kpi(c[2], "Positions", f"{n_long + n_short}", f"{n_long} long · {n_short} short")
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
t_pos, t_trades, t_comm, t_rules = st.tabs(["Positions", "Trades", "Committee", "Rules & method"])

with t_pos:
    if pos.empty:
        st.caption("No open positions.")
    else:
        v = pos.copy()
        v["pnl"] = v["market_value"] - v["cost_basis"]
        v["pnl_pct"] = (v["market_value"] / v["cost_basis"] - 1) * 100 * v["direction"].map({"LONG": 1, "SHORT": -1})
        v["weight"] = v["market_value"] / last["nav"] * 100
        v = v.sort_values("weight", key=abs, ascending=False)
        st.dataframe(v[["ticker", "sector", "direction", "entry_date", "entry_price", "last_price",
                        "market_value", "weight", "pnl", "pnl_pct"]], hide_index=True,
                     column_config={
                         "ticker": "Ticker", "sector": "Sector", "direction": "Side", "entry_date": "Entry",
                         "entry_price": st.column_config.NumberColumn("Entry px", format="%.2f"),
                         "last_price": st.column_config.NumberColumn("Last px", format="%.2f"),
                         "market_value": st.column_config.NumberColumn("Market value", format="%.0f"),
                         "weight": st.column_config.NumberColumn("% NAV", format="%.2f"),
                         "pnl": st.column_config.NumberColumn("P&L $", format="%.0f"),
                         "pnl_pct": st.column_config.NumberColumn("P&L %", format="%.2f")})

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
    c3.metric("Analyst", "AI model (Groq)" if r["analyst"] == "groq" else "Template")
    for w in r.get("warnings", []) + r.get("analyst_log", []):
        st.caption(f"⚠ {w}")
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
                               ("Size", "9_size")]:
                st.markdown(f"<div class='field'><b>{label}:</b> {m[key]}</div>", unsafe_allow_html=True)
            st.caption(" · ".join(f"{d['column']}={d['value']}" for d in m["4_data_points"]))
    if h.get("boundaries"):
        st.caption("Boundaries: " + " · ".join(f"{k}: {v}" for k, v in h["boundaries"].items()))

with t_rules:
    rules = json.loads((POLICY / "standing_rules.json").read_text())
    limits = json.loads((POLICY / "limit_policy.json").read_text())
    veto = json.loads((POLICY / "pm_overrides.json").read_text())
    st.markdown(f"""
**How a trade happens**
1. **Screen (code):** about 100 large-cap US stocks ranked on 12-1 momentum. Longs: top names above their 200-day average. Shorts: weakest names below it.
2. **Harness (code, 18 tests):** ranks the top 5, checks every memo, sizes by volatility, checks limits.
3. **S1 analyst (AI model in live mode):** writes each memo and cites the screen's numbers. Misquoted numbers are caught and stopped.
4. **PM standing rules:** trade only memos that pass every check, with conviction ≥ {rules['min_conviction']}, at most {rules['max_new_trades_per_day']} new trades a day.
5. **Exits:** stop loss {rules['stop_loss_pct']}%, max holding {rules['max_holding_days']} trading days, or the signal fades.
6. **PM veto:** edit `fund/policy/pm_overrides.json` on GitHub. Vetoed now: {', '.join(veto['veto_tickers']) or 'none'}.

**Limits** (version {limits['version']}): position {limits['limits']['max_position_pct_nav']}% · sector {limits['limits']['max_sector_pct_nav']}% · gross {limits['limits']['max_gross_pct_nav']}% · net ±{limits['limits']['max_net_pct_nav']}% of NAV.

**Honest caveats**
- Paper trading: fills at the daily close with {rules['transaction_cost_bps']} bps cost; no slippage model, no borrow cost on shorts.
- Replay uses today's large-cap list (survivorship bias) and the template analyst, because an AI model trained on later data could leak hindsight into past decisions.
- Momentum is a well-known factor; this demonstrates a controlled process, not a proprietary edge.
""")
