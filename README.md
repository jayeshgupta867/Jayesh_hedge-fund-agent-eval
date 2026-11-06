# Hedge Fund Agent Evaluation

Design and evaluation of an agentic workflow for a hedge fund front office: from pending trade ideas to a one-page trade memo a portfolio manager can approve, reject or resize.

Built as part of the IE University Edge Course (Master in Finance), V2 passed all 13 design checks.

## The problem
Which parts of a hedge fund's idea-to-trade process can an AI agent safely do, and which must stay with code or a human? The workflow stops **before execution**: nothing it produces moves money.

## The design
- **One research agent** writes shortlist reasons and a falsifiable thesis per idea (catalyst, key risk, falsifier, numeric exit level). It only drafts.
- **A deterministic script harness** does all the arithmetic: data pull, ranking, position sizing, limit checks, and a check that every cited number matches the database.
- **Two PM gates:** the portfolio manager selects ideas from the shortlist, then approves, rejects or resizes each memo. Only the PM commits anything.
- **Read-only by design:** the agent has no database access at all; any database write by the workflow stops the run.

## Key design decisions
- **Control breaches surfaced, not hidden.** In the test data, all three pending ideas already had positions opened without PM approval. The workflow flags them above the shortlist instead of pitching or ignoring them; a shortlist of zero candidates is a valid result.
- **No fake numbers.** Missing volatility or liquidity means the size is WITHHELD, not guessed.
- **Circular evidence declared.** The agent only has the analyst's own data, so every citation is labelled "not independent evidence", and its conviction score can never exceed the analyst's.
- **One agent, not two.** A scored decision showed a second "critic" agent would share the same context and be fooled by the same plausible thesis; script checks are more reliable.

## V1 → V2
After feedback from practitioners (a hedge fund manager and a senior wealth manager):
- **Adapted:** risk lives at the aggregate book level, so every memo now states that correlation risk was NOT ASSESSED (no data), so a limit PASS is never read as "safe for the book".
- **Accepted:** every data field names an owner.
- **Rejected:** stop-loss rules (out of scope, post-execution) and a second verification agent.

See `CHANGELOG.md` for the reasoning.

## Repository contents
| File | What it covers |
|---|---|
| `L1_model.md` – `L9_graph.md` | Design layers: model, prompt, context, memory, skills, workflow, harness, loop, trace |
| `CHANGELOG.md` | V1 → V2 and V3 → V4 decisions and reasons, incident log |
| `REDTEAM.md` | Red-team attacks and mutation check results |
| `PASS_REVIEW.md` | Final 13-check design review |

## Evaluation
The `evaluation/` folder contains a runnable Python version of the harness, tested against 18 scenarios: normal runs, edge cases (sector at its limit, unknown sector, stale or mixed data snapshots) and traps (a wrong citation, an inflated conviction score, positions opened without PM approval, a database write attempt). All 18 pass, and a mutation check confirms the tests fail when a safeguard is removed.

The research agent is stubbed, so this evaluates the harness, not the model. See `evaluation/README.md` for the full results table and how to run it.

## Live paper fund
The `fund/` folder turns the design into a running paper-trading fund: $1m of simulated money, long/short US large caps with a SPY hedge, benchmarked to SPY. No real money is involved. Dashboard: https://jayesh-agentic-fund.streamlit.app

Every US trading day after the close, GitHub Actions:
1. runs all harness, engine and red-team tests plus a mutation check, and **does not trade if any fail**;
2. downloads prices and runs the **data gate**: no intraday prices, no stale feed, unconfirmed jumps and frozen prices quarantined;
3. runs a momentum screen (code picks every name and number);
4. passes the ideas through the unchanged harness, where an AI analyst (Groq) drafts each memo and the harness checks every citation, the conviction cap and every limit;
5. runs the **book checks**: at most 3% of average daily volume, correlation with the existing book (above 0.70 halves the size, above 0.85 rejects it), no crowded shorts, and the analyst **challenges its own input** (it can escalate, never approve);
6. books trades the PM's standing rules pre-approve, and **queues anything flagged for a manual PM sign-off** (`fund/policy/pm_approvals.json`);
7. keeps three books (long, short, SPY hedge to near-zero beta), revalues the fund and commits the results to `fund/state/`. The git history is the audit trail.

The dashboard (`streamlit_app.py`) shows NAV vs SPY, drawdown, positions, P&L by book, trades, each day's committee decisions with every check, trades awaiting the PM, the red-team results, plus a **Replay** mode and the interactive **Harness lab**.

| Path | What it is |
|---|---|
| `fund/engine/` | Prices, data gate, screen, AI analyst, book risk, approvals, paper ledger, daily run |
| `fund/policy/` | PM-owned mandate, limits, standing rules, veto and approvals (the engine only reads these) |
| `fund/state/` | Committed results: `live/` and `replay/`, plus the latest red-team report |
| `fund/tests/` | 59 tests: 16 engine, 28 red-team attacks, 15 v4 features |
| `fund/redteam.py` | Runs the attacks, then switches each safeguard off to prove the tests depend on it |
| `.github/workflows/fund.yml` | The daily schedule, the replay button and the fail-safes |
| `dashboard/`, `streamlit_app.py` | The public dashboard |

## Safety: preventing irreversible actions
A trade is an action that cannot be undone. The design lets the AI draft and question, and never size, approve or book:

| Layer | Stops |
|---|---|
| Data gate | Booking intraday or stale prices, trading or stopping out on a bad print |
| Harness | Hallucinated numbers, inflated conviction, the agent writing its own size or PM decision, database writes |
| Book checks | Hidden concentration, illiquid trades, crowded shorts; the analyst can only escalate |
| PM sign-off | Flagged trades booked without a human; approvals are bound to the exact trade by a token, valid for one run, and ignored if written by the automation |
| Fail-safes | Trading with a failing test or an untested safeguard; the run changing anything outside `fund/state` |

`REDTEAM.md` lists every attack (prompt injection, approval bypass, forged and expired approvals, self-approval, self-modification, glitches, stale data, look-ahead, crowded shorts, corrupted configuration) and the mutation check. Run it with `python -m fund.redteam`.

Caveats: fills at the daily close with 10 bps plus a square-root impact estimate, no borrow costs; replay uses today's large-cap list (survivorship bias) and the template analyst, so hindsight cannot leak into past decisions; closing-auction volume and order-book depth are NOT ASSESSED (no free data). See `CHANGELOG.md` for the v4 changes and the incident log.
