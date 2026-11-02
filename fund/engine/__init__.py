"""Paper-trading engine built around the evaluation harness.

The harness in evaluation/harness is reused unchanged: it ranks ideas, checks the
agent's memos, sizes positions and checks limits. This package adds real prices,
a screen, a paper ledger and the PM's standing rules.
"""
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[2] / "evaluation"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))
