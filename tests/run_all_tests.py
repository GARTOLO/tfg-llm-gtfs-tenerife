"""
Simple test runner to automate the project's tests.

Usage:
  python tests/run_all_tests.py           # runs pytest for unit tests
  python tests/run_all_tests.py --eval    # additionally runs the evaluation script (requires MCP/LLM)
  python tests/run_all_tests.py --pytest-args "-k plan_trip -q"  # pass custom args to pytest

The script executes pytest programmatically as a subprocess and optionally runs
`tests/eval_agent.py` (this script connects to the local MCP and requires the
MCP server + Google API available).

This runner is intentionally minimal (uses subprocess) so it behaves like running
commands from the shell and preserves exit codes and console formatting.
"""

import argparse
import subprocess
import sys
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTEST_DEFAULT_ARGS = ["-v"]


def run_pytest(pytest_args):
    cmd = [sys.executable, "-m", "pytest"] + pytest_args
    print("\nRunning pytest:\n  ", " ".join(shlex.quote(p) for p in cmd), "\n")
    proc = subprocess.run(cmd)
    return proc.returncode


def run_eval_agent():
    eval_script = ROOT / "tests" / "eval_agent.py"
    if not eval_script.exists():
        print("eval_agent.py not found, skipping evaluation run.")
        return 1
    cmd = [sys.executable, str(eval_script)]
    print("\nRunning eval_agent script (requires MCP/Gemini):\n  ", " ".join(shlex.quote(p) for p in cmd), "\n")
    proc = subprocess.run(cmd)
    return proc.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run project tests and optional evaluation script")
    parser.add_argument("--eval", action="store_true", help="Also run tests/eval_agent.py (requires MCP/Gemini)")
    parser.add_argument("--pytest-args", type=str, default="",
                        help="Extra arguments to pass to pytest (quoted string)")
    args = parser.parse_args()

    pytest_args = PYTEST_DEFAULT_ARGS
    if args.pytest_args:
        pytest_args += shlex.split(args.pytest_args)

    code_pytest = run_pytest(pytest_args)

    code_eval = 0
    if args.eval:
        code_eval = run_eval_agent()

    # Exit with non-zero if any of the steps failed
    if code_pytest != 0 or code_eval != 0:
        print(f"\nOne or more test steps failed (pytest={code_pytest}, eval={code_eval}).")
        sys.exit(code_pytest or code_eval)

    print("\nAll requested test steps completed successfully.")
    sys.exit(0)

