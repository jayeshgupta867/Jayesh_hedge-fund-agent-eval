"""Test configuration, plus the mutation check used by `python -m fund.redteam`.

When FUND_MUTATION names a safeguard below, that safeguard is switched off for the whole
test session. The red-team runner then expects specific tests to FAIL: a test that still
passes with its safeguard removed is not really testing it. Mutations live here, in test
code, never in the engine.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "evaluation"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _mutations():
    from fund.engine import analyst, approvals, cli, dataguard, risk, screen
    from harness import run as harness_run

    orig_features = screen.features
    pass_corr = {"result": "PASS", "action": "none", "rho_book": None, "max_pair": None,
                 "pair_ticker": None, "note": "mutated: check removed"}
    return {
        "no_session_check": (dataguard, "drop_unfinished_session", lambda prices, now, cfg: (prices, [])),
        "no_freshness_check": (dataguard, "check_freshness", lambda prices, now, cfg: []),
        "no_glitch_quarantine": (dataguard, "quarantine", lambda *a, **k: ({}, [])),
        "no_correlation_check": (risk, "correlation_check", lambda *a, **k: dict(pass_corr)),
        "no_crowding_check": (risk, "crowding_check", lambda *a, **k: {"result": "PASS", "action": "none",
                                                                       "note": "mutated"}),
        "no_token_check": (approvals, "token_matches", lambda item, a: True),
        "no_approval_expiry": (approvals, "is_expired", lambda *a, **k: False),
        "no_bot_author_check": (approvals, "BOT_AUTHORS", set()),
        "no_challenge_sanitizer": (analyst, "sanitize_challenges",
                                   lambda raw: [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []),
        "no_write_guard": (cli, "guard_state_root", lambda p: Path(p)),
        "no_memo_checks": (harness_run, "check_memo", lambda *a, **k: []),
        "lookahead_in_screen": (screen, "features",
                                lambda prices, date, tickers: orig_features(prices, prices.dates[-1], tickers)),
    }


def pytest_configure(config):
    name = os.environ.get("FUND_MUTATION")
    if not name:
        return
    table = _mutations()
    if name not in table:
        raise SystemExit(f"unknown mutation {name}")
    module, attr, value = table[name]
    setattr(module, attr, value)
