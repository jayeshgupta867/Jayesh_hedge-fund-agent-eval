# Changelog — fund v3 → v4

Feedback from the final Edge Course session (5 Nov 2026), from Gianluca (hedge fund CIO) and Hemal (peer), plus problems found in the first live week. Same rule as V1 → V2: accept · adapt · reject, with the reason.

## Findings

| # | Source | Finding | Decision | What changed | Why |
|---|---|---|---|---|---|
| 1 | Gianluca | Let the agent be "more critical and questioning of the input received". | adapt | `analyst.py` challenge step: the analyst reviews each trade-ready idea against code-computed facts (e.g. share of the momentum from a single day) and may add a note or escalate to the PM. Output sanitised to note/escalate. | It can question, but it still cannot decide. An agent that can approve or upsize would break the core design. |
| 2 | Gianluca | Always check the data is live and there has been no glitch. | accept | `dataguard.py`: closed-session check, staleness stop, frozen-price and unconfirmed-jump quarantine with a second source, benchmark glitch stops the day. | Bad data is the cheapest way to make an irreversible mistake. The first live day already had one (incident 1). |
| 3 | Gianluca | Check every idea's correlation with the existing book: high correlation is replication, i.e. concentration. | accept | `risk.correlation_check`: 60-day signed correlation to the book and to each position; above 0.70 halves the size, above 0.85 rejects. Replaces V2's "NOT ASSESSED". | V2 had no price history, so I declared it. The fund has prices now, so I can compute it honestly. Day 1 bought five chip/software stocks together (incident 3). |
| 4 | Gianluca | Liquidity: no more than ~3% of average daily volume, ~20% of the closing auction, look at L1–L3 and options. | adapt | 3% ADV cap per trade, square-root impact cost, capacity estimate. Closing auction and order book declared NOT ASSESSED. | The ADV rule I can compute from free data. Auction and order-book data are paid, so I declare them instead of faking them. |
| 5 | Gianluca | Define the strategy and asset class first; everything follows from it. | accept | `fund/policy/mandate.json`, shown on the dashboard. | Every limit and rule only makes sense relative to a mandate. |
| 6 | Gianluca | The long book, the short book and the hedge are three different logics. Avoid crowded shorts (GameStop, VW). | accept | Short stop 10% (long 12%); shorts with > 10% of float sold short are not added, unknown short interest goes to the PM; SPY hedge book to near-zero beta; P&L by book. | A short has unbounded loss, so it needs its own rules. Splitting the books shows where the money is made or lost. |
| 7 | Gianluca | Systematic trades inside the model's parameters sign automatically; discretionary ones are signed by hand. | accept | Standing rules sign clean trades; flagged trades wait in `pending.json` for `pm_approvals.json`. Approvals bind the exact trade (token), are valid one run, and are ignored if committed by the bot. | It is how his fund works, and it puts the human exactly where the uncertainty is. |
| 8 | Hemal | Backtests must not use future data. | accept | Red-team test R20 poisons all future prices and checks 30 days of decisions are identical; a mutation proves the test works. | A backtest that peeks is worse than none: it gives false confidence. |
| 9 | Paolo | Course feedback (demo, more technical sessions). | — | No fund change. | Course feedback, not fund feedback. |

## Incident log (first live week)

| # | What happened | Impact | Fix |
|---|---|---|---|
| 1 | 2 Nov: the first live run was started at 16:17 UTC, while US markets were open, so five positions were booked at intraday prices; the evening run then skipped the day as already processed. | P&L on those five positions overstated by about $2.7k (0.27% of NAV). History left as is (git is the audit trail). | Never book an open session (`dataguard.drop_unfinished_session`, red-team R17). |
| 2 | 2–5 Nov: every Groq call failed with an HTTP error. Groq shut down `llama-3.3-70b-versatile` on 16 Aug 2026. The template wrote every memo, but the dashboard said "AI model (Groq)". | No wrong trades (template memos are fully checked), but the report was misleading. | Default model `openai/gpt-oss-120b`, optional `GROQ_MODEL` repository variable, HTTP status logged, dashboard shows what actually wrote each memo (R05). |
| 3 | 2 Nov: five highly correlated chip/software longs bought on day 1; three (AMD, MU, ADI) hit their stops on 5 Nov. | The five day-1 names lost about $14.7k of the fund's −$19.0k (long book −$18.3k, short book −$0.8k). | Correlation with the book (R21). |
| 4 | Found while writing red-team R04: a malformed model reply (data points as text) crashed the whole run. | None (found before release). | Malformed replies become an empty draft the harness stops. |
| 5 | Found while testing R10 with real git: the approvals-author check always returned "unknown". | None: it failed closed (all approvals ignored). | Fixed path handling; R10 now uses a real git repo. |

## Policy versions
`limit_policy.json` fund-1 → fund-2 (correlation, liquidity, data sections) · `standing_rules.json` rules-1 → rules-2 (short stop, short book, hedge, approvals) · new `mandate.json`, `pm_approvals.json`.

---

# Changelog — v1 → v2

`v2/` is a copy of `v1/`. It changes in a refinement session with the orchestrator: finding by finding, you decide accept · adapt · reject and say why; every change is shown before and after and written only when you confirm. Your reasons go here in your own words. `v1/` is never modified.

Built from v1 on: 2026-10-29 · Refinement session on: 2026-10-29

## Summary

Findings received: 4 — from peer: 0 (no peer review received; my partner has not produced a v1, so V2 reflects banker feedback only) · from the finance session: 4 · own: 0  
Accepted: 1 · Adapted: 1 · Rejected: 2

## Entries

| # | Source | Finding (quoted) | Decision (accept · adapt · reject) | What changed (file § section) | Why, in my words |
| --- | --- | --- | --- | --- | --- |
| 1 | Finance session (Live Session 2) — Gianluca | Risk matters most at the aggregate book level, through correlation with existing positions, not position by position. | adapt | `v2/L6_workflow.md` § A2 (memo field 10 and done-when), § A3 (U8 check); `v2/L3_context.md` § A6 (data gaps) — U8's limit report adds 'Aggregate/correlation risk: NOT ASSESSED – no correlation data', shown at the top of every memo, so a full PASS on limits is never read as 'safe for the book' | The data has no volatility or correlation, so I can't compute a marginal-risk check honestly. A check I can't compute must be declared, not faked. |
| 2 | Finance session (Live Session 2) — Alejandro | Every data field in the memo should name its owner as well as its source. | accept | `v2/L9_graph.md` § A7 (Evidence: evidence.md records snapshot ID, source table and owner for every data field in the memo) | If nobody owns a number, nobody can defend it in front of the PM. |
| 3 | Finance session (Live Session 2) — Gianluca | Add hard stop-loss rules (e.g. suspending at −5%). | reject | — | My workflow covers only the step before a trade, and loss monitoring after execution belongs to a separate workflow with live P&L data. |
| 4 | Finance session (Live Session 2) — Alejandro | A 'plausible repeated mistake' calls for a second verification agent. | reject | — | The A5 score stays at 0. A second model shares the same context and can be persuaded by the same mistake; the citation-value check and the conviction cap address it more reliably. |

## Changes not prompted by feedback

| # | What changed (file § section) | Why, in my words |
| --- | --- | --- |
| 1 | `my_kitchen/policy/limit_policy.json` created as a placeholder (owner: PM; limit values null, to be set by the PM). Outside `v2/`; no layer file changed. | So the path my design references exists. |

## Closing

- `v1/` untouched: yes
- `handoff.json` regenerated from `v2/` on: 2026-10-29
- `v2/PASS_REVIEW.md`: PASS
