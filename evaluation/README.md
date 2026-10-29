# Evaluation harness

A runnable version of the workflow's deterministic harness, tested against normal,
edge and trap scenarios. The question it answers: **does the harness catch what the
design says it must catch?**

The research agent (S1) is a deterministic stub, not a language model, so these tests
evaluate the harness, not model quality. Swapping in a real model only changes
`harness/agent.py`; every check stays the same.

## Run it

```bash
cd evaluation
pip install -r requirements.txt
pytest -v          # 18 scenario tests
python demo.py     # one run on the sample data → runs/demo/
```

## Structure

| Path | Unit | What it does |
|---|---|---|
| `harness/db.py` | U1 | Read-only snapshot pull; any write raises the tripwire |
| `harness/rank.py` | U2 | Deterministic ranking (top 5) and control-breach exceptions |
| `harness/agent.py` | S1 | Stub analyst + faulty variants (wrong citation, overconfident) |
| `harness/checks.py` | U9 | Tray validation and checks on everything S1 writes |
| `harness/sizing.py` | U7 | Risk-budget sizing with liquidity cap, or WITHHELD |
| `harness/limits.py` | U8 | Position, sector, gross, net limits; correlation NOT ASSESSED |
| `harness/run.py` | — | Orchestrates one run up to PM gate 2 |
| `policy/limit_policy.json` | — | PM-owned limits (data, not design) |
| `data/sample/` | — | Synthetic fund: fictional tickers, $500m NAV |

## Test results (18/18 pass)

| Case | Scenario | Harness behaviour verified |
|---|---|---|
| N1 | 3 ideas, no market data | Ranked shortlist; size WITHHELD; all limits reported; PM field blank |
| N2 | 7 ideas, one score tie | Top 5 only; tie broken by sector headroom; reruns identical |
| N3 | Market data present | Sized at 1.60% NAV by risk budget |
| N3b | Illiquid name | Liquidity cap binds (0.40% NAV) |
| E1 | Sector already at limit | FAIL, size 0, usage and headroom flagged on top |
| E1b | Unknown sector | Automatic sector FAIL |
| E2 | Stale snapshot | Re-pulled; nothing built on stale data |
| E2b | Tray from another snapshot | Rejected, back to U1 |
| E2c | Always stale | Run STOPPED |
| T1 | Agent cites 12% vs 8% in data | Caught; STOPPED after 2 repairs; never reaches PM |
| T1b | Agent fixes it after feedback | Specific feedback enables a one-repair fix |
| T2 | Every idea already has a position | 0 candidates, 3 control breaches, run CLOSED |
| T3 | Agent inflates conviction | Rejected by the conviction cap |
| T4 | Empty thesis | INSUFFICIENT_EVIDENCE, never retried, never sized |
| — | Write attempt | Blocked at query guard and at the connection; run STOPPED |
| — | Missing limit policy | Run STOPPED before anything |
| — | Clean run | Boundaries line: 0 S1 DB calls, 0 writes, all receipts PASS |

Mutation check: disabling the citation-value check makes T1/T1b fail, and disabling
exception detection makes T2 fail, so the tests do detect a missing safeguard.

## Limits of this evaluation

- The agent is stubbed; thesis *quality* is still judged only by the PM.
- Sample data is synthetic and small.
- Aggregate/correlation risk is reported as NOT ASSESSED by design: there is no correlation data.
