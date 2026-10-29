# L3 · Context — the pantry

What every run loads, and which sources this kitchen is allowed to use. Filled from A6. This is the kitchen's CLAUDE.md.

Status: decided on 2026-10-29

## A6 · Pantry — decided on 2026-10-29

- The counter — what every run loads by default (keep it small): S1 loads only the thesis format (memo fields 2–6 and their rules), the citation rule (every claim cites table and date), the conviction scale (1–5) and its role boundary (read-only, drafts only, no sizing or limits). S1 does not load the fund's limit policy, because U5 and U6 do not use it; limits belong to the harness.
- The pantry — the whitelist of authorized sources, named one by one ("the internet" is not a source): all read-only. (1) hedge_funds.idea_pipeline — Pending ideas, theses, expected return, horizon, conviction (read by U1). (2) hedge_funds.positions_risk — current book, sector, market value, % of NAV, VaR (read by U1 and U8). (3) my_kitchen/policy/limit_policy.json — the fund limit policy, outside v1 and referred to by path, read only by the harness (U8), edited only by the PM; limits are data, the check is design, and each run's trace records which version of the file it used. Data gaps: volatility, liquidity, correlation and sector for new tickers have no source, deliberately; aggregate/correlation risk is therefore reported as NOT ASSESSED on every memo; size is WITHHELD and an unknown sector is an automatic sector-limit FAIL, because naming a market-data source that cannot be connected would turn a missing input into a promise. The v2 fix is a price-and-volume source to calculate volatility and liquidity, plus a sector reference table, maintained by whoever owns the data.
- Role-specific context — loaded only when a role actually needs it: S1 has no database connection; it sees only what U1 and U2 hand it (the selected ideas' full idea_pipeline rows, each tagged with table and date so it can cite them), never the limits or the full book, which keeps its reasoning off sizing by design. The harness sees the limits, the book and the numbers from the handoff, but never the thesis text, because sizing does not need it (A1, independence).

**Decision:** S1 loads a small counter and only the tagged rows U1 hands it, while the harness alone reads the two hedge_funds tables and the PM-owned limit policy, and missing market data stays WITHHELD in v1 rather than invented.
