# L6 · Workflow — the order + the recipe

What this kitchen produces, for whom, and the steps that produce it. Filled from A2 and A3.

Status: decided on 2026-10-29 · revised on 2026-11-08 (sizing formula and limit values stated, see § Sizing and limits)

## A2 · The order — decided on 2026-10-29

- Objective in one sentence — Deliver a ranked shortlist, then a one-page trade memo (thesis, script-calculated size and limit report) for each idea the PM selects, to the portfolio manager.
- Client of the result — The portfolio manager (PM). The packets speed up two decisions: which ideas go forward to a full thesis (gate 1), and whether to open a position and at what size (gate 2).
- The reviewable packet — Two packets. (A) Shortlist (gate 1, lighter): 0–5 ranked candidates, each with ticker, direction, a one-line reason, key screening metrics and the snapshot timestamp, below an Exceptions section listing every Pending idea that already has a position (idea ID, ticker, direction, market value, % of NAV, settlement status, and the note 'Position exists without PM approval – control breach'); what happens to an exception is the PM's call. (B) Trade memo (gate 2), fields in this order: (1) ticker, long/short, date; (2) thesis summary (2–3 sentences); (3) catalyst and expected timing; (4) supporting data points, each citing its database source and date; (5) key risk; (6) what would prove it wrong, plus a numeric exit level; (7) agent's proposed conviction score and reason; (8) expected return, volatility, liquidity; (9) proposed size from the script (formula and values in § Sizing and limits); (10) limit report: pass/fail with usage, limit and headroom for position size (5% NAV), sector concentration (25% NAV), gross exposure (150% NAV) and net exposure (±40% NAV), with liquidity enforced as a cap inside the size, plus the line 'Aggregate/correlation risk: NOT ASSESSED – no correlation data', shown at the top of every memo so a full PASS on limits is never read as 'safe for the book' (risk matters most at aggregate book level through correlation with existing positions, and the data has no volatility or correlation, so a marginal-risk check cannot be computed honestly and is declared rather than faked); (11) PM decision: approve / reject / resize, plus final conviction score. The per-position cap is applied by the script; when a book-level limit is already used up by existing positions, the script sets the proposed size to 0 and flags FAIL with the limit name, current usage, the limit and remaining headroom, and the memo still goes to the PM, who decides whether to cut another position to make room.
- Three things this workflow does NOT do: 1. Does not send or execute orders. 2. Does not backtest or develop strategies. 3. Does not set or override fund limits, or the PM's final conviction score.
- Done when / proof — Shortlist: every candidate has all five fields (ticker, direction, one-line reason, screening metrics, snapshot timestamp); candidates are ranked and the ranking rule is stated at the top; every screening metric comes from the database in a snapshot not older than the last market close; 0–5 candidates, and if 0 the Exceptions section explains why. Trade memo: fields 1–10 are filled and field 11 is left blank for the PM (the PM's signature is the gate, not part of done); a MISSING or WITHHELD entry counts as filled only in fields 8 and 9, only for data the database does not hold, and only if it names the missing input and the reason; a blank field always fails; every thesis claim cites a database data point with a date; the exit level is a number, not a description; the size comes from the script, not the agent; the limit report shows a result for every limit, the line 'Aggregate/correlation risk: NOT ASSESSED – no correlation data' appears at the top of every memo, and any FAIL appears at the top of the memo with limit name, current usage, the limit and remaining headroom; the snapshot is not older than the last market close, and the memo states 'price as-of date unknown – pulled at <timestamp>' and shows the idea's age from date_generated.

**Decision:** The workflow delivers two reviewable packets to the PM, a ranked shortlist of zero to five candidates with exceptions on top for gate 1 and an 11-field trade memo for gate 2, bounded by three non-goals and complete only when every yes/no criterion passes with field 11 left for the PM.

## A3 · The recipe — decided on 2026-10-29

6 to 12 units. Every unit names all four. A unit without a check is not done.

| n | Input | Action | Artifact | Check |
| --- | --- | --- | --- | --- |
| 1 | Ideas with status = 'Pending' in idea_pipeline + positions_risk (Script) | Pull data; look up sector in positions_risk; move any idea that already has a position to Exceptions | Candidate table, exceptions list, book snapshot | Required fields not null; every pull stamped with a snapshot ID and timestamp, not older than the last market close |
| 2 | Candidate table (Script) | Rank by conviction × annualised expected return (expected return ÷ horizon in years); tie-break by most sector headroom | Top 0–5 candidates | Rule stated; ≤ 5 names; same input gives same ranking |
| 3 | Top 5 + pipeline rows from U1, tagged with table and date (Agent) | Write a one-line reason per candidate | reasons.json {idea_id, reason}; the harness builds shortlist.md and attaches the Exceptions section on top | All five fields present per candidate; metrics match U1 |
| 4 | Shortlist packet (PM, gate 1) | Select / reject each candidate; rule on each exception | Selected list | Every candidate marked; PM updates status in idea_pipeline |
| 5 | Selected idea rows from U1, tagged with table and date (Agent) | Draft thesis, catalyst, data points, key risk, falsifier and exit level (memo fields 2–6) | Thesis draft | Every claim cites table and date; exit level is a number |
| 6 | memo_draft_<idea_id>.md (Agent) | Propose conviction score (1–5, the idea_pipeline scale) with reason only; the harness fills memo fields 1 and 8 from U1's extract | conviction_<idea_id>.json + reason in memo field 7 | Score is an integer within 1–5 and not above the pipeline conviction |
| 7 | Conviction, volatility, ADV, NAV (Script) | Apply the sizing formula: size % NAV = 0.6 × (conviction ÷ 5) ÷ annualised volatility, capped so the position can be exited in 5 days at ≤ 20% of ADV | Memo field 9 with the note 'risk-budget sized' or 'liquidity-capped', or 'WITHHELD – missing volatility/liquidity' | Output reproducible to 4 decimals; missing input named; formula version recorded |
| 8 | Proposed size + book (Script) | Check every limit (position ≤ 5%, sector ≤ 25%, gross ≤ 150%, net within ±40% of NAV) and cut the size to the smallest headroom | Memo field 10 | Result, usage and headroom for every limit; book-level breach or unknown sector sets size to 0; the report always carries 'Aggregate/correlation risk: NOT ASSESSED – no correlation data' at the top of the memo |
| 9 | Fields 1–10 (Script) | Run the A2 done-when checklist | Final memo, field 11 blank | All checks pass; a failure returns to the unit that owns it |
| 10 | Final memo (PM, gate 2) | Approve / reject / resize + final conviction | PM decision | Field 11 completed; PM updates status in idea_pipeline |

Loops: gate-1 reject is final for that idea (U2 reruns without rejected names if the PM asks for alternatives); gate-2 resize with a new target size returns to U8 → U9 → PM; gate-2 new final conviction returns to U7; gate-2 reject ends the workflow for that idea. The workflow is read-only on the database; the PM writes every status update.

**Decision:** Ten units carry an idea from a read-only data pull through two PM gates, with scripts owning data, ranking, sizing, limits and completeness, and the agent owning only the written reasoning.

## Sizing and limits — revised on 2026-11-08

The formula is design; the values are data owned by the PM in `limit_policy.json` (version recorded in every trace). The values below are the starting values the harness runs with (`evaluation/policy/limit_policy.json`, version demo-1).

**U7 · sizing formula**

    raw size (% NAV)    = risk budget × (conviction ÷ 5) ÷ annualised volatility
    liquidity cap (% NAV) = 100 × liquidation days × max ADV participation × ADV ÷ NAV
    proposed size        = min(raw size, liquidity cap)

- **Risk budget 0.6% NAV.** A conviction-5 position is sized so that its one-standard-deviation annual move is 0.6% of NAV; conviction 1 gets a fifth of that (0.12%). Size × volatility = risk budget × conviction ÷ 5, so a more volatile stock gets a smaller position for the same conviction.
- **Liquidity cap: exit within 5 trading days at no more than 20% of average daily volume.** With these values the cap equals one day's ADV.
- **Missing volatility or ADV:** size WITHHELD, never estimated. In the course database neither exists, so every size there is WITHHELD; when `market_data` supplies them (the evaluation sample does), the formula runs.
- The conviction used is the agent's proposal after the cap (never above the pipeline's); a PM change to the final conviction at gate 2 re-runs U7.

**U8 · limits and how they cut the size**

| Limit | Value (% NAV) | Measured as | Headroom for a new trade |
| --- | --- | --- | --- |
| Position size | 5 | the new position | 5 |
| Sector concentration | 25 | sum of absolute exposure in the idea's sector | 25 − sector usage |
| Gross exposure | 150 | sum of absolute exposure | 150 − gross |
| Net exposure | ±40 | longs minus shorts | 40 − net for a long, 40 + net for a short |
| Aggregate/correlation risk | — | NOT ASSESSED (no correlation data) | — |

Final size = min(proposed size, every headroom). If any headroom is already ≤ 0, or the sector is unknown, the size is 0 and that limit FAILs at the top of the memo with usage, limit and headroom.

**Worked examples** (the Harness lab's sample fund: NAV $500m, gross 41%, net +32%, Energy 25%, Technology 10.5%; computed by `harness/sizing.py` and `harness/limits.py`)

| Idea | Conviction | Volatility | ADV | Raw size | Liquidity cap | Binding | Final size |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IDEA-001 JOVA long, Healthcare | 4 | 30% | $40m | 0.6 × 0.8 ÷ 0.30 = 1.60% | 8.0% | risk budget | **1.60% NAV ($8.0m)** |
| IDEA-002 KYTE long, Technology | 3 | 45% | $8m | 0.6 × 0.6 ÷ 0.45 = 0.80% | 1.6% | risk budget | **0.80% NAV ($4.0m)** |
| IDEA-003 LUMN short, Financials | 4 | 25% | $60m | 0.6 × 0.8 ÷ 0.25 = 1.92% | 12.0% | risk budget | **1.92% NAV ($9.6m)** |
| IDEA-004 MERA long, Energy | 5 | missing | missing | WITHHELD | — | sector at 25% of 25% | **0, sector FAIL** |

**Live paper fund.** The fund in `fund/` runs the same formula and limits with its own PM file (`fund/policy/limit_policy.json`): risk budget 1.0% NAV, net ±50%, plus at most 3% of ADV per trade, correlation with the book (size halved above 0.70, rejected above 0.85), stops at 12% (long) and 10% (short), and a SPY hedge to near-zero beta. See `README.md` and `CHANGELOG.md`.
