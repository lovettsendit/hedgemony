"""Run every suite and report one verdict.

    python3 tests/run_all.py

No test framework is required and none is installed. The suites are plain scripts that print
what they checked and exit non-zero on failure, so they run identically on a developer's
machine and in a pipeline with nothing set up.
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_sandbox.py", "test_scan.py", "test_contracts.py", "test_cli.py",
          "test_end_to_end.py", "test_generated.py", "test_board.py",
          "test_environment.py", "test_proof.py", "test_regressions.py"]


def main():
    results = []
    for suite in SUITES:
        path = os.path.join(HERE, suite)
        if not os.path.exists(path):
            continue
        print("=" * 72)
        print(f"  {suite}")
        print("=" * 72)
        completed = subprocess.run([sys.executable, path], env={**os.environ,
                                                                "PYTHONDONTWRITEBYTECODE": "1"})
        results.append((suite, completed.returncode == 0))

    print("=" * 72)
    for suite, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {suite}")
    failed = [s for s, ok in results if not ok]
    print("=" * 72)
    print(f"  {len(results) - len(failed)} of {len(results)} suites passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
