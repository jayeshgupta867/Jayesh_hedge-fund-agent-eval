# L4 · Memory — the notebook

What this kitchen remembers between runs, who owns it and when it expires. Filled from A6. No opaque memory by default: if nothing persists, say so and say why.

Status: decided on 2026-10-29

## A6 · Persistent memory — decided on 2026-10-29

- What persists: No agent memory. Only (a) idea_pipeline.status, which already records every PM decision, and (b) the run folders: each run's shortlist, memos, evidence, ticket and trace, including the version of the limit policy file used.
- Source: status is written by the PM at U4 and U10; run folders are written by the harness, append-only (it can only add new runs; S1 cannot write there).
- Owner: the PM owns both.
- Retention: run folders in my_kitchen/runs/<run-date>/ (course template: packet, evidence, ticket, trace) are kept 5 years from the run date, in line with typical investment-firm record-keeping.
- Deletion rights: nobody deletes during retention; after expiry, deletion requires PM approval.
- Expiry: 5 years after the run date.
- Or: not applicable in this kitchen, by design, because: separate agent memory is excluded by design — it would create a second, unowned record that could drift from the database, and past theses could bias new ones.

**Decision:** Nothing persists for the agent; the PM-owned database status and the append-only run folders, kept five years, are the only memory and audit trail.
