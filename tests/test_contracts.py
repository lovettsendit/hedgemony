"""Does contract checking report what held, what did not, and what it could not decide?

THE FOUR STATES EXIST SO THAT UNKNOWN IS NEVER PRINTED AS FINE. `OK` and `VIOLATED` are
verdicts. `NO_CONTRACT` and `UNCHECKED` are not -- they say the behaviour of this file is
unknown, for two different reasons, and both are tested here to make sure neither can quietly
collapse into a pass.

The most important test in this file is the last one in the first section: a file that states
nothing is never executed at all. That is what lets the tool be pointed at unfamiliar code
without running it -- the decision to execute is made from parsing, before anything runs.
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from hedgemony.contracts import check_contracts, has_contracts     # noqa: E402
from hedgemony.sandbox import Limits                                # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  [{'ok  ' if condition else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def write(body, name="probe.py"):
    directory = tempfile.mkdtemp(prefix="hedgemony-contract-")
    path = os.path.join(directory, name)
    with open(path, "w") as fh:
        fh.write(textwrap.dedent(body))
    return path


def main():
    print("\nTHE FOUR STATES\n")

    result = check_contracts(write('''
        def double(x):
            """Twice x.

            >>> double(4)
            8
            """
            return x * 2
        '''))
    check("OK -- every stated example held",
          result.status == "OK" and not result.findings, f"{result.examples} example(s)")

    # The case the whole layer exists for: a real function, called correctly, doing the wrong
    # thing. Every name here exists, so nothing else in this tool can see it.
    result = check_contracts(write('''
        import math

        def pages_needed(items, per_page):
            """How many pages are needed to show every item.

            >>> pages_needed(10, 3)
            4
            """
            return math.floor(items / per_page)
        '''))
    check("VIOLATED -- a real function doing the wrong thing is caught",
          result.status == "VIOLATED" and len(result.findings) == 1,
          result.findings[0]["detail"] if result.findings else "")

    result = check_contracts(write('''
        def add(a, b):
            """Adds two numbers."""
            return a + b
        '''))
    check("NO_CONTRACT -- nothing was stated, so nothing was checked",
          result.status == "NO_CONTRACT", "reported as unknown, not as a pass")

    # A file with no stated examples must never be executed. Proving it: the file would create
    # a marker on import, and the marker must not exist afterwards.
    marker = os.path.join(tempfile.mkdtemp(prefix="hedgemony-marker-"), "ran.txt")
    path = write(f'''
        open({marker!r}, "w").write("executed")

        def add(a, b):
            return a + b
        ''')
    result = check_contracts(path)
    check("a file that states nothing is never executed at all",
          result.status == "NO_CONTRACT" and not os.path.exists(marker),
          "decision made by parsing, before anything runs")

    print("\nWHAT CANNOT BE DECIDED IS SAID SO\n")

    result = check_contracts(write('''
        raise RuntimeError("fails at import")

        def f():
            """
            >>> f()
            1
            """
            return 1
        '''))
    check("UNCHECKED -- a file that raises on import is reported, not passed",
          result.status == "UNCHECKED", (result.error or "")[:52])

    result = check_contracts(write('''
        import time

        def slow():
            """
            >>> slow()
            1
            """
            time.sleep(60)
            return 1
        '''), limits=Limits(wall_seconds=3, cpu_seconds=30))
    check("UNCHECKED -- a run stopped by a limit is never reported as a failed contract",
          result.status == "UNCHECKED" and not result.findings, result.error or "")

    print("\nDETAIL A READER CAN ACT ON\n")

    result = check_contracts(write('''
        def total(values):
            """Sum of the values.

            >>> total([1, 2])
            3
            >>> total([10, 20])
            30
            >>> total([])
            0
            """
            return sum(values) + 1
        '''))
    check("each failing example is reported separately",
          result.status == "VIOLATED" and len(result.findings) == 3,
          f"{len(result.findings)} of {result.examples} examples failed")

    lines = [f["line"] for f in result.findings]
    check("each finding carries the line of its own example",
          len(set(lines)) == 3 and all(l > 0 for l in lines), f"lines {lines}")

    result = check_contracts(write('''
        def risky(x):
            """
            >>> risky(0)
            1
            """
            return 1 / x
        '''))
    check("an example that raises is a violation, not a crash",
          result.status == "VIOLATED" and len(result.findings) == 1,
          result.findings[0]["detail"][:64] if result.findings else "")

    print("\nCOUNTING WITHOUT RUNNING\n")

    check("stated examples are counted by parsing",
          has_contracts('def f():\n    """\n    >>> f()\n    1\n    """\n') == 1)
    check("a file with no examples counts zero",
          has_contracts("def f():\n    return 1\n") == 0)
    check("a file that will not parse counts zero rather than crashing",
          has_contracts("def broken(:\n") == 0)

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
