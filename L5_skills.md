# L5 · Skills — the techniques

The house style: the repeatable procedures, templates, connections and rules this kitchen relies on. Filled from A6. Which station may use which of them is decided per station in L7 (B2).

Status: decided on 2026-10-29

## A6 · Scaffolding audit — decided on 2026-10-29

| Item | Type (Skill · MCP/API · Hook/Script) | What it does | When NOT to use it |
| --- | --- | --- | --- |
| Thesis format + memo template | Skill | House style for memo fields 1–11, thesis fields 2–6 and the citation rule (S1) | Not for any arithmetic |
| Shortlist template | Skill | House style for the shortlist packet (five fields per candidate, ranking rule on top, Exceptions section) | Not for ranking, which is the script's job |
| hedge_funds connection | MCP/API | Read-only access to idea_pipeline and positions_risk, harness only (U1, U8), never S1 | Not for writes; status is written by the PM |
| U1 pull, U2 ranking, U7 sizing, U8 limit check, U9 completeness and citation-value check | Hook/Script | Deterministic data pull, ranking, sizing, limit check against my_kitchen/policy/limit_policy.json, completeness check and match of every cited value against the database | Not for anything that needs judgment (reasons, thesis, conviction) |

Skill = repeatable house style · MCP/API = live access · Hook/Script = deterministic rule.

**Decision:** Judgment work uses two Skills (templates only), live data reaches the kitchen through one read-only MCP connection held by the harness, and every rule that code can enforce is a Script.
