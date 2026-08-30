"""The layers, tested on code no human wrote, checked as a user would check it.

WHY A SEPARATE SUITE. A fixture written by hand to be caught proves that the tool catches
fixtures written by hand to be caught. Every file used here is unmodified output from a small
local code model, saved exactly as produced. Nothing in them was arranged, and the failures
they contain are the ones the model actually made.

THREE FILES, CHOSEN TO COVER THE THREE OUTCOMES THAT MATTER:

    generated_sample.py            invented names, no stated examples
    generated_with_contracts.py    NO invented names, and still wrong
    generated_contracts_hold.py    nothing wrong -- the negative control

The middle file is the important one. It contains zero fabricated names, so every name-based
check in this tool -- and every type checker -- passes it clean. It is still wrong, and the
model's own stated example is what proves it. Without that layer the file reads as fine.

The last file exists because a suite where every fixture fails cannot tell a working detector
from one that flags everything.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLES = os.path.join(ROOT, "examples")
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  [{'ok  ' if condition else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def hedgemony(*args):
    """Run the tool the way a person runs it: the command, on a path, reading what comes out."""
    done = subprocess.run([sys.executable, "-m", "hedgemony", *args], cwd=ROOT,
                          capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    return done


def scan_one(path, *extra):
    done = hedgemony(path, "--json", *extra)
    return next(iter(json.loads(done.stdout).values())), done.returncode


def main():
    names = os.path.join(EXAMPLES, "generated_sample.py")
    wrong = os.path.join(EXAMPLES, "generated_with_contracts.py")
    right = os.path.join(EXAMPLES, "generated_contracts_hold.py")

    for path in (names, wrong, right):
        if not os.path.exists(path):
            print(f"  missing fixture: {path}")
            return 1

    print("\nINVENTED NAMES IN GENERATED OUTPUT\n")

    entry, code = scan_one(names)
    flagged = {f["token"] for f in entry["findings"]}
    check("the invented attributes are flagged",
          {"console.table", "console.progress"} <= flagged, ", ".join(sorted(flagged)))
    check("the run exits non-zero so a pipeline notices", code == 1)

    # Ground truth from the installed library, in both directions. The three real methods on
    # the same object must be silent, or the tool is just flagging everything it sees.
    from rich.console import Console
    check("ground truth: the flagged names really do not exist",
          not hasattr(Console, "table") and not hasattr(Console, "progress"))
    check("ground truth: real methods on the same object were not flagged",
          all(hasattr(Console, n) for n in ("print", "rule", "log"))
          and not any(f"console.{n}" in flagged for n in ("print", "rule", "log")),
          "print, rule, log all exist and none were flagged")
    check("a file with no stated examples reports NO_CONTRACT, not a pass",
          entry["contracts"]["status"] == "NO_CONTRACT")

    print("\nTHE CASE NAME CHECKING CANNOT SEE\n")
    print("  generated code, zero invented names, and still wrong\n")

    entry, code = scan_one(wrong)
    check("no fabricated names are found in this file",
          len(entry["findings"]) == 0, f"rate {entry['rate']} per 100 lines")
    check("and its stated examples do not hold",
          entry["contracts"]["status"] == "VIOLATED",
          f"{len(entry['contracts']['findings'])} of {entry['contracts']['examples']} failed")

    details = [f["detail"] for f in entry["contracts"]["findings"]]
    for detail in details:
        print(f"    {detail}")
    check("the finding names the contradiction in full",
          all("was stated to give" in d and "but gave" in d for d in details))
    check("the run exits non-zero even though every name exists", code == 1,
          "a name-only checker would have exited 0 here")

    # The bug is confirmed independently: the function is called directly and the result
    # compared with what its own docstring claimed. This is the tool's verdict checked against
    # the same interpreter a user's code would run on.
    sys.path.insert(0, EXAMPLES)
    import generated_with_contracts as subject                 # noqa: E402
    actual = subject.format_byte_count(1024)
    check("running the function confirms the reported bug",
          actual != "1.0 KB", f"format_byte_count(1024) returns {actual!r}, not '1.0 KB'")

    print("\nTHE NEGATIVE CONTROL -- generated code that is fine\n")

    entry, code = scan_one(right)
    check("no fabricated names", not entry["findings"])
    check("every stated example holds", entry["contracts"]["status"] == "OK",
          f"{entry['contracts']['examples']} example(s) held")
    check("a clean file exits zero", code == 0)

    done = hedgemony(right)
    check("and the output still refuses to call it correct",
          "does NOT mean the code is correct" in done.stdout)

    print("\nWHAT THE TWO LAYERS ADD UP TO\n")

    done = hedgemony(EXAMPLES, "--json")
    everything = json.loads(done.stdout)
    named = sum(len(v["findings"]) for v in everything.values())
    contracts = sum(len(v["contracts"]["findings"]) for v in everything.values())
    checked = sum(1 for v in everything.values() if v["contracts"]["status"] in ("OK",
                                                                                "VIOLATED"))
    print(f"    {len(everything)} generated file(s)")
    print(f"    {named} invented name(s) found by asking the interpreter")
    print(f"    {contracts} stated example(s) that did not hold")
    print(f"    {checked} file(s) had behaviour checked at all")
    check("both layers found something no single layer would have",
          named > 0 and contracts > 0,
          "names alone would miss the logic bug; contracts alone would miss the invented names")

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
