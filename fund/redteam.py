"""Red-team report: run every attack, then prove each safeguard is what stops it.

    python -m fund.redteam                       # print the summary
    python -m fund.redteam --json fund/state/redteam.json --md REDTEAM.md

Step 1 runs fund/tests/test_redteam.py (one test per attack).
Step 2 is a mutation check: each safeguard is switched off in turn (fund/tests/conftest.py)
and the attacks it should stop are re-run. They must now FAIL; a safeguard whose tests still
pass is not really tested. Exit code 1 if any attack succeeds or any mutation survives.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = "fund/tests/test_redteam.py"

# safeguard switched off -> attacks that must then succeed (tests that must fail)
MUTATIONS = {
    "no_memo_checks": ("Harness memo checks (citations, conviction cap, owned fields)",
                       ["test_r01", "test_r02", "test_r03", "test_r04"]),
    "no_challenge_sanitizer": ("Challenge output limited to note/escalate", ["test_r06"]),
    "no_token_check": ("Approval token binds the exact trade", ["test_r07"]),
    "no_approval_expiry": ("Approvals expire after one trading day", ["test_r08"]),
    "no_bot_author_check": ("Approvals committed by the automation are ignored", ["test_r10"]),
    "no_write_guard": ("Engine cannot write outside fund/state", ["test_r12"]),
    "no_glitch_quarantine": ("Unconfirmed price jumps and frozen feeds quarantined",
                             ["test_r13", "test_r14", "test_r18", "test_r19"]),
    "no_freshness_check": ("Stale price feed stops the live run", ["test_r16"]),
    "no_session_check": ("Open session never booked (2 Nov incident)", ["test_r17"]),
    "lookahead_in_screen": ("Screen sees only data up to the decision date", ["test_r20"]),
    "no_correlation_check": ("Correlation with the book (concentration)", ["test_r21"]),
    "no_crowding_check": ("Crowded or unverifiable shorts blocked", ["test_r22", "test_r23"]),
}


def _pytest(args: list[str], env_extra: dict | None = None) -> tuple[int, dict[str, str]]:
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "out.xml"
        env = {**os.environ, **(env_extra or {})}
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               f"--junitxml={xml}", *args], cwd=ROOT, env=env, capture_output=True, text=True)
        results = {}
        if xml.exists():
            for case in ET.parse(xml).getroot().iter("testcase"):
                failed = any(child.tag in ("failure", "error") for child in case)
                skipped = any(child.tag == "skipped" for child in case)
                results[case.get("name")] = "FAIL" if failed else "SKIP" if skipped else "PASS"
        return proc.returncode, results


def _attacks() -> list[dict]:
    sys.path.insert(0, str(ROOT))
    from fund.tests import test_redteam as mod

    out = []
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if not name.startswith("test_r"):
            continue
        lines = [ln.strip() for ln in (fn.__doc__ or "").strip().splitlines()]
        meta = {k: "" for k in ("attack", "expected", "category")}
        for ln in lines[1:]:
            k, _, v = ln.partition(":")
            if k in meta:
                meta[k] = v.strip()
        rid, _, title = lines[0].partition(" · ") if lines else (name, "", name)
        out.append({"id": rid, "test": name, "title": title, **meta})
    return sorted(out, key=lambda a: a["id"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    ap.add_argument("--md", type=Path)
    ap.add_argument("--no-mutations", action="store_true")
    a = ap.parse_args(argv)

    attacks = _attacks()
    _, res = _pytest([SUITE])
    for at in attacks:
        at["result"] = res.get(at["test"], "MISSING")
    mutations = []
    if not a.no_mutations:
        for key, (safeguard, tests) in MUTATIONS.items():
            k = " or ".join(tests)
            _, mres = _pytest([SUITE, "-k", k], {"FUND_MUTATION": key})
            hit = {t: r for t, r in mres.items() if any(t.startswith(x) for x in tests)}
            caught = bool(hit) and all(r == "FAIL" for r in hit.values())
            mutations.append({"mutation": key, "safeguard": safeguard, "tests": sorted(hit) or tests,
                              "caught": caught})

    ok_attacks = sum(at["result"] == "PASS" for at in attacks)
    ok_mut = sum(m["caught"] for m in mutations)
    summary = {"run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
               "attacks_blocked": ok_attacks, "attacks_total": len(attacks),
               "mutations_caught": ok_mut, "mutations_total": len(mutations),
               "ok": ok_attacks == len(attacks) and ok_mut == len(mutations),
               "attacks": attacks, "mutations": mutations}

    print(f"Attacks blocked: {ok_attacks}/{len(attacks)}")
    for at in attacks:
        if at["result"] != "PASS":
            print(f"  ✗ {at['id']} {at['title']}: {at['result']}")
    if mutations:
        print(f"Mutations caught: {ok_mut}/{len(mutations)}")
        for m in mutations:
            if not m["caught"]:
                print(f"  ✗ removing '{m['safeguard']}' was NOT detected by {', '.join(m['tests'])}")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(summary, indent=1))
    if a.md:
        a.md.write_text(_markdown(summary))
    return 0 if summary["ok"] else 1


def _markdown(s: dict) -> str:
    lines = [
        "# Red-team results",
        "",
        f"Generated by `python -m fund.redteam` on {s['run_at_utc']} UTC. GitHub Actions re-runs it before every "
        "trading day: if any attack succeeds or any mutation survives, the fund does not trade.",
        "",
        f"**{s['attacks_blocked']}/{s['attacks_total']} attacks blocked · "
        f"{s['mutations_caught']}/{s['mutations_total']} safeguards proven by mutation**",
        "",
        "## Attacks",
        "",
        "| ID | Scenario | Attack | Expected safe outcome | Category | Result |",
        "|---|---|---|---|---|---|",
    ]
    for at in s["attacks"]:
        mark = "✅ blocked" if at["result"] == "PASS" else f"❌ {at['result']}"
        lines.append(f"| {at['id']} | {at['title']} | {at['attack']} | {at['expected']} | {at['category']} | {mark} |")
    if s["mutations"]:
        lines += ["", "## Mutation check", "",
                  "Each safeguard is switched off in turn. The attacks it should stop must then succeed "
                  "(their tests fail). If they still passed, the test would not really be testing that safeguard.",
                  "", "| Safeguard removed | Tests that must fail | Detected |", "|---|---|---|"]
        for m in s["mutations"]:
            lines.append(f"| {m['safeguard']} | {', '.join(m['tests'])} | {'✅ yes' if m['caught'] else '❌ no'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
