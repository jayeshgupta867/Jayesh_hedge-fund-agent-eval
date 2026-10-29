# Trade memo IDEA-003

> **Aggregate/correlation risk: NOT ASSESSED – no correlation data**

1. **Ticker / direction / date:** LUMN SHORT · 2026-10-29 · idea age from 2026-10-22
2. **Thesis:** Deposit outflows compress net interest margin
3. **Catalyst:** Evidence of the thesis within the 9-month horizon
4. **Data points:**
   - expected_return = 0.1 — idea_pipeline.expected_return @ SNAP-443a63f0f0a5 (source: analyst's pipeline row – not independent evidence)
   - horizon_months = 9 — idea_pipeline.horizon_months @ SNAP-443a63f0f0a5 (source: analyst's pipeline row – not independent evidence)
5. **Key risk:** The thesis rests only on the analyst's own pipeline row
6. **Falsifier / exit:** Expected return below zero at the halfway point of the horizon · exit level -0.05
7. **Proposed conviction:** 4 – No independent evidence, so conviction stays at the analyst's level
8. **Return / vol / liquidity:** 0.1 / 0.25 / 60000000 (owners: expected_return – analyst (idea_pipeline); volatility/adv – market data owner)
9. **Size:** 1.92% NAV (risk-budget sized)
10. **Limit report:**
    - position size: **PASS** (usage 0.0, limit 5.0, headroom 5.0)
    - sector concentration (Financials): **PASS** (usage 0.0, limit 25.0, headroom 25.0)
    - gross exposure: **PASS** (usage 41.0, limit 150.0, headroom 109.0)
    - net exposure: **PASS** (usage 32.0, limit 40.0, headroom 72.0)
    - aggregate/correlation risk: **NOT ASSESSED** (usage None, limit None, headroom None) — no correlation data — a limit PASS is not 'safe for the book'
11. **PM decision:** ____________

_Policy demo-1 · snapshot SNAP-443a63f0f0a5_
