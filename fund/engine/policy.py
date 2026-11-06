"""Loading and validating the PM-owned policy files.

A policy file that is missing, unreadable or incomplete stops the run before anything
trades (fail closed). The engine only ever READS fund/policy; it never writes there.
"""
from __future__ import annotations

import json
from pathlib import Path


class PolicyError(Exception):
    """A policy file is missing, malformed or has an invalid value: nothing trades."""


LIMIT_KEYS = ["max_position_pct_nav", "max_sector_pct_nav", "max_gross_pct_nav", "max_net_pct_nav"]
RULE_KEYS = ["min_conviction", "max_new_trades_per_day", "stop_loss_pct", "max_holding_days",
             "signal_exit_percentile", "transaction_cost_bps", "starting_capital"]

DEFAULT_RISK = {
    "correlation": {"window_days": 60, "min_obs": 40, "halve_above": 0.70, "reject_above": 0.85},
    "liquidity": {"max_trade_pct_adv": 3.0, "impact_coefficient": 0.1},
    "data": {"max_one_day_move": 0.25, "max_benchmark_move": 0.10, "confirm_tolerance": 0.02,
             "frozen_days": 5, "max_stale_business_days": 4, "session_close_ny": "16:30"},
}
DEFAULT_RULES = {
    "stop_loss_short_pct": None,  # falls back to stop_loss_pct
    "allow_shorts": True,
    "short_book": {"max_short_interest_pct_float": 10.0},
    "hedge": {"enabled": False, "instrument": "SPY", "target_net_beta_pct": 0.0,
              "rebalance_band_pct": 5.0, "beta_window_days": 60},
    "approvals": {"valid_trading_days": 1, "max_price_drift_pct": 3.0},
}


def read_json(path: str | Path) -> dict:
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise PolicyError(f"{path.name} missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"{path.name} unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"{path.name} must be a JSON object")
    return data


def _positive(name: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise PolicyError(f"{name} must be a positive number, got {value!r}")


def load_limit_policy(path: str | Path) -> dict:
    pol = read_json(path)
    if "version" not in pol:
        raise PolicyError("limit policy has no version")
    limits = pol.get("limits")
    if not isinstance(limits, dict):
        raise PolicyError("limit policy has no 'limits' section")
    for k in LIMIT_KEYS:
        _positive(f"limits.{k}", limits.get(k))
    sizing = pol.get("sizing") or {}
    for k in ("risk_budget_pct_nav", "max_liquidation_days", "max_adv_participation"):
        _positive(f"sizing.{k}", sizing.get(k))
    for section, defaults in DEFAULT_RISK.items():
        merged = {**defaults, **(pol.get(section) or {})}
        pol[section] = merged
    c = pol["correlation"]
    if not 0 < c["halve_above"] <= c["reject_above"] <= 1:
        raise PolicyError("correlation thresholds must satisfy 0 < halve_above <= reject_above <= 1")
    _positive("liquidity.max_trade_pct_adv", pol["liquidity"]["max_trade_pct_adv"])
    return pol


def load_rules(path: str | Path) -> dict:
    rules = read_json(path)
    for k in RULE_KEYS:
        if k not in rules:
            raise PolicyError(f"standing rules missing '{k}'")
    for k in ("max_new_trades_per_day", "stop_loss_pct", "max_holding_days", "starting_capital"):
        _positive(k, rules[k])
    for k, v in DEFAULT_RULES.items():
        if isinstance(v, dict):
            rules[k] = {**v, **(rules.get(k) or {})}
        else:
            rules.setdefault(k, v)
    if rules["stop_loss_short_pct"] is None:
        rules["stop_loss_short_pct"] = rules["stop_loss_pct"]
    return rules


def load_overrides(path: str | Path) -> dict:
    ov = read_json(path)
    for k in ("veto_tickers", "close_tickers"):
        v = ov.setdefault(k, [])
        if not isinstance(v, list) or not all(isinstance(t, str) for t in v):
            raise PolicyError(f"pm_overrides.{k} must be a list of tickers")
    return ov
