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
| `CHANGELOG.md` | V1 → V2 decisions and reasons |
| `PASS_REVIEW.md` | Final 13-check design review |

## Evaluation
The `evaluation/` folder contains a runnable Python version of the harness, tested against 18 scenarios: normal runs, edge cases (sector at its limit, unknown sector, stale or mixed data snapshots) and traps (a wrong citation, an inflated conviction score, positions opened without PM approval, a database write attempt). All 18 pass, and a mutation check confirms the tests fail when a safeguard is removed.

The research agent is stubbed, so this evaluates the harness, not the model. See `evaluation/README.md` for the full results table and how to run it.
