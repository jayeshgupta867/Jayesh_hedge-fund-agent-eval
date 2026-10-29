# L1 · Model — the protein

Which model each station runs on, at which tier, and why. Filled from B1. One section per station; a one-cook kitchen has one station, S1.

Status: decided on 2026-10-29

## S1 · Research Analyst — decided on 2026-10-29

- Tier: ☐ cheap worker ☒ mid-tier executor ☐ frontier boss-verifier
- Why — what this station must be good at, and what it must never be trusted with: S1 verifies nothing (scripts and the PM do), so it does not need the frontier boss-verifier tier; "one strong model" means a capable mid-tier model. It must be good at reading structured rows, writing a falsifiable argument, citing precisely and following a fixed format. It must never be trusted with numbers for sizing, limits, ranking, final conviction or approval. Volume is at most 5 memos per run, so cost is not the constraint; if the A8 KPI fails because theses are weak (review time over 10 minutes), upgrading the tier becomes a v2 change.

**Decision:** S1 runs on a mid-tier executor model, because it drafts and never verifies, and a tier upgrade is reserved for v2 if weak theses break the review-time KPI.
