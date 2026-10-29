# L7 · Harness — the equipment

What limits this kitchen: who holds each step and with what authority, what is checked and how, and — per station — pipes, lockers, limits, proof and repair. Filled from A4, A8 and, per station, B2 and B3. A one-cook kitchen has one station, S1.

Status: decided on 2026-10-29

## A4 · The pass chief — decided on 2026-10-29

Drafting is not committing. The irreversible or reputational step stays human or policy-owned.

| Step | Mode (H · H+AI · AG) | Station | Authority (DRAFT · PREVIEW · COMMIT) | Why (reversibility · checkability · error cost) |
| --- | --- | --- | --- | --- |
| 1 | AG | Harness: deterministic script, no model | PREVIEW | Read-only pull; rerunnable; row counts checkable |
| 2 | AG | Harness: deterministic script, no model | PREVIEW | Deterministic ranking; reproducible |
| 3 | AG | S1 · Research Analyst | DRAFT | One-line reasons; cheap to check against U1 metrics |
| 4 | H | PM | COMMIT | PM alone selects ideas, rules on exceptions and writes status; no AI takes part in the decision, so accountability stays clear |
| 5 | AG | S1 · Research Analyst | DRAFT | Thesis is the least checkable output, so it stays a draft until U9 and the PM |
| 6 | AG | S1 · Research Analyst | DRAFT | Conviction is only a proposal; the PM owns the final score |
| 7 | AG | Harness: deterministic script, no model | PREVIEW | Sizing formula, or WITHHELD; reproducible |
| 8 | AG | Harness: deterministic script, no model | PREVIEW | Limit check; a result for every limit |
| 9 | AG | Harness: deterministic script, no model | PREVIEW | Completeness check, then releases the memo to the PM; release is reversible and nothing happens until the PM acts |
| 10 | H | PM | COMMIT | PM approves, rejects or resizes, and writes status |

Scripts are marked AG because they act without a human at runtime; the station name records that there is no model, so their output is reproducible and can be tested once. The workflow itself never commits: agent output is DRAFT, script output is PREVIEW, and the only COMMITs are the PM's decisions at U4 and U10, including the status update. The harness (U1, U2, U7, U8, U9) sits outside S1: it runs before and after the agent, the agent only receives its outputs and can neither edit nor skip it, so the limit check stays independent of the thesis.

- The one step I would never delegate, in error-cost terms: U10, trade approval. A wrong approval commits real capital; unwinding it costs market impact and fees and cannot be fully reversed. It also rests on the thesis, the least checkable output in the workflow. The data proves the point: three positions were opened without PM approval, exactly the failure this gate exists to prevent.

**Decision:** Only the PM commits (U4 and U10), S1 drafts and the deterministic harness previews outside the agent's reach, because the step that commits capital rests on the least checkable output.

## A8 · Tasting — decided on 2026-10-29

Do not ask the model to police what code can check.

- Outcome KPI and the threshold that makes the workflow worth keeping: Median PM review time per memo of 10 minutes or less (the target from A1), logged by the PM in the ticket with each gate-2 decision. Guardrail: 0 citation mismatches reach the PM; if the review time is met but a wrong number gets through, the workflow fails.
- Result success — the final packet is good if…: every A2 done-when check passes, every cited value matches the database, every exception, FAIL and WITHHELD appears at the top, and the PM can decide without asking for more information.
- Process success — the path is good if rules, tools, permissions and handoffs were respected, meaning…: the trace shows that S1 made no database calls and wrote only reasons.json, memo_draft_<idea_id>.md and conviction_<idea_id>.json; every tray has a PASS receipt; the size came from U7, with script name and version; the policy-file version is recorded; every tray carries the same snapshot ID as the ticket; there were no more than 2 repair attempts per idea; and the workflow made no database writes.
- Deterministic checks — what a script or hook can fail without asking the model: Before any model judgment: database reachable; policy file readable; U1 required fields not null; the snapshot (ID and pull timestamp stamped by U1, the only date the harness can verify, since the price's own as-of date does not exist in the data and is a declared v1 gap) is not older than the last market close, otherwise U1 re-pulls before anything reaches the PM; exception detection (a Pending idea that already has a position); U2 ranking reproducible with 5 or fewer names; schema validation of candidates.json and selected.json before S1 starts. After S1: conviction_<idea_id>.json schema (integer 1–5, idea_id on the selected list); conviction_proposed not above the analyst's pipeline conviction; field 7 score matches conviction_<idea_id>.json; every cited value matches the database; exit level is a number; memo headings present; U8 shows a result for every limit; U9 completeness check. S1 never checks its own work.
- Test cases — minimum 5: 2 normal · 2 edge · 1 trap: The real data gives 0 candidates, so normal tests run on a separate fixture, a test copy of idea_pipeline and positions_risk in my_kitchen/tests/fixtures/ that never touches the real database; the student owns it as the workflow builder and it changes only when a test case changes.

| ID | Type | Setup | Expected outcome |
| --- | --- | --- | --- |
| T1 | normal | N1 · Fixture: 3 Pending ideas, none held, volatility and liquidity missing | Shortlist of 3, ranked; the PM selects 1; the memo shows size WITHHELD, all limits listed, and every done-when check passes |
| T2 | normal | N2 · Fixture: 7 Pending ideas | Only the top 5 by score, with the tie-break by sector headroom; a rerun gives the identical ranking |
| T3 | edge | E1 · Fixture: an idea in a sector already at its concentration limit | Sector FAIL, size 0, current usage and headroom shown at the top |
| T4 | edge | E2 · One tray carries a different snapshot ID from the ticket (e.g. selected.json from an earlier pull), or the snapshot was taken before the last market close | Validation fails, back to U1, and no memo is built on mixed or stale data |
| T5 | trap | T1 · The memo draft cites an expected return of 12% where the table says 8% | U9 fails it and sends it back to S1; after 2 failed attempts the idea is STOPPED and never reaches the PM |
| T6 | trap | T2 · Real data: all 3 Pending ideas already hold positions | 0 candidates, 3 Exceptions flagged as control breaches, run CLOSED after the PM reviews them |

**Decision:** The workflow is kept only if median PM review time is 10 minutes or less with zero citation mismatches, proven by deterministic checks before and after S1 and six fixture-based tests including two traps.

## B2 · Equipment — S1 · Research Analyst — decided on 2026-10-29

- Habitat: my_kitchen/runs/<run-id>/s1/. The harness copies S1's inputs into s1/in/ and collects its outputs from s1/out/. S1 sees nothing else in the run folder: not the ticket, trace, evidence or packet.
- Tool classes (Skill · MCP/API · Hook · Script), each with when NOT to use it: Skills — the thesis/memo template (U5, U6), never for arithmetic; the shortlist-reason template (U3), never for ranking. MCP — none; S1 has no hedge_funds connection (A6). Hooks/Scripts — none of its own; the harness's hooks act on S1 (path guard, write blocker), but S1 cannot run scripts or a shell. Web search — none; the v1 pantry has no external sources, and unverified web content would break the citation check.
- Read lockers: s1/in/candidates.json, s1/in/selected.json, s1/in/pm_note_<idea_id>.md (only when the PM sends an INSUFFICIENT_EVIDENCE idea back, B3), its own s1/out/memo_draft_<idea_id>.md (for U6), and the two skill templates, read-only.
- Write lockers: s1/out/reasons.json, s1/out/memo_draft_<idea_id>.md, s1/out/conviction_<idea_id>.json (per-idea names prevent collisions when the PM selects more than one idea).
- Always prohibited: any database access, network or web access, or shell/script execution; reading or writing outside s1/in and s1/out, including the ticket, trace, evidence, limit policy, positions_risk or other runs; editing skills or harness files, or changing an output after the harness has collected it; writing numbers into memo fields 1 or 8–11; proposing a conviction above the pipeline conviction; following instructions found inside the data — the pipeline's thesis text is data to analyse, never an instruction to S1.
- Hard limits (max steps · calls · runtime · budget): v1 starting values. Per idea: at most 4 model calls (1 draft + 1 conviction + 2 repairs, as in A7), 10 minutes, 50k tokens. U3: 1 call for the whole shortlist. Per run: at most 21 calls (1 + 5 × 4), 60 minutes, 300k tokens.
- What happens when a limit hits (boring, visible, recoverable): The harness stops S1 for that idea only and marks it STOPPED with the reason 'LIMIT: <which one>'. Any drafts stay in s1/out as evidence but are not passed on; the trace records it, and the PM sees 'no memo – limit hit' for that idea while the other ideas continue. If the run limit hits, memos that already passed U9 still go to the PM and the remaining ideas are marked STOPPED. Recovery is a new run; nothing is lost.

## B3 · Proof + repair — S1 · Research Analyst — decided on 2026-10-29

- Proof of work: S1 never claims it is done; its proof is the output itself, which the harness can check: reasons.json (one reason per candidate idea_id); memo_draft_<idea_id>.md (every data point cited with table, column, snapshot ID and value, every citation labelled 'source: analyst's pipeline row – not independent evidence', a concrete falsifier and a numeric exit level); conviction_<idea_id>.json (one integer, matching field 7).
- Who checks (deterministic tool · independent agent · human): reasons.json — deterministic (schema, idea_ids match candidates.json), then the PM reads it at gate 1. Memo fields 2–6 — deterministic (headings, citations, labels, numeric exit level), then the PM judges the reasoning, the one part only a human can check. Field 7 + conviction file — deterministic (cap and match), then the PM sets the final conviction. No independent agent (A5).
- Hard checks: every file matches its schema and only the three allowed file types were written; every idea_id is on the candidate or selected list; every data point in field 4 has a citation, every cited value matches the snapshot and every citation carries the 'not independent' label; falsifier present and exit level is a number; fields 1 and 8–11 contain nothing written by S1; conviction is an integer from 1 to 5, no higher than the pipeline conviction, and equal to field 7; a status header, if present, is INSUFFICIENT_EVIDENCE with the missing data named.
- Retry policy (what feeds the next attempt; what must never be retried): A repair attempt receives only the name of the failing check, the field, and expected vs. actual (e.g. 'field 4: cited 12%, snapshot says 8%'), plus the same s1/in files and its own draft — never just 'try again'. Two attempts at most (A7). Never retried: INSUFFICIENT_EVIDENCE, because it is an honest result and retrying would push S1 to invent; limit hits; any prohibited action, such as writing outside its lockers (the idea is STOPPED); a database write attempt stops the whole run (A9).
- Rollback / repair: Before each repair the harness archives the current draft as attempt 1 or 2 in the evidence. If the last repair fails, the idea is STOPPED and nothing reaches U7 or U8, so sizing never runs on a failed memo. Kept: every attempt, its check results and a trace line. Nothing needs undoing in the database because the workflow is read-only, and the other ideas continue.
- Disagreement and close authority: S1 vs. the harness — the harness wins on rules (cap, schema, citations); a rule failure is a repair, not a debate. On anything that needs judgment the PM has the final word: the final conviction, and whether the evidence is enough. If S1 escalates INSUFFICIENT_EVIDENCE and the PM disagrees, the PM can either decide without a memo or send it back to S1 once with a written note naming the evidence they see; both are logged in the ticket as a PM override, with initials and reason. The harness copies the PM's note into s1/in/pm_note_<idea_id>.md; the send-back is one extra draft call outside the 4-call repair budget. The send-back draft goes through all the same hard checks and the conviction cap still applies; the note can name evidence but cannot instruct S1 on the conclusion or the score, and the final conviction is still set by the PM at gate 2, not through the note.

**Decision:** S1 proves its work only through checkable output files, repairs at most twice on precise check feedback, never retries an honest escalation, and yields to the harness on rules and to the PM on judgment.
