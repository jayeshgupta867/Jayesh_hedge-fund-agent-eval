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
