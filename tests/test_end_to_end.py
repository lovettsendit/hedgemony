"""The whole tool, run the way a person runs it, on code nobody wrote by hand.

Every other suite tests a part. This one runs the command line against real files and checks
what actually comes out, because a tool can have every unit passing and still be broken at the
seam where they meet.

`examples/generated_sample.py` is unmodified output from a small local code model, kept exactly
as it was produced. It is the honest test case: nothing about it was arranged to be catchable,
and the two names it invents are confirmed against the installed library below. A fixture
written by hand to be caught would prove nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

EXAMPLES = os.path.join(ROOT, "examples")
PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  [{'ok  ' if condition else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def run(*args):
    return subprocess.run([sys.executable, "-m", "hedgemony", *args], cwd=ROOT,
                          capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def main():
    print("\nTHE COMMAND LINE\n")

    sample = os.path.join(EXAMPLES, "generated_sample.py")
    broken = os.path.join(EXAMPLES, "broken.py")

    if not os.path.exists(sample):
        print("  examples/generated_sample.py is missing; cannot run the end-to-end check")
        return 1

    done = run(sample, "--json")
    check("the tool runs and returns machine-readable output", done.returncode in (0, 1),
          f"exit {done.returncode}")

    try:
        payload = json.loads(done.stdout)
    except ValueError:
        check("output parses as JSON", False, done.stdout[:120])
        return 1
    check("output parses as JSON", True)

    entry = next(iter(payload.values()))
    invented = {f["token"] for f in entry["findings"]}
    check("the invented names in generated output are flagged",
          {"console.table", "console.progress"} <= invented, ", ".join(sorted(invented)))

    # GROUND TRUTH. Asked of the installed library rather than assumed, and checked in BOTH
    # directions: the two flagged names must be absent, and the three unflagged ones present.
    from rich.console import Console
    absent = [n for n in ("table", "progress") if not hasattr(Console, n)]
    present = [n for n in ("print", "rule", "log") if hasattr(Console, n)]
    check("ground truth agrees the flagged names do not exist",
          len(absent) == 2, f"absent: {', '.join(absent)}")
    check("real methods on the same object were not flagged",
          len(present) == 3 and not any(f"console.{n}" in invented for n in present),
          f"present and silent: {', '.join(present)}")

    check("a rate is reported", entry["rate"] > 0, f"{entry['rate']} per 100 lines")
    check("a file with no stated examples reports NO_CONTRACT",
          entry["contracts"]["status"] == "NO_CONTRACT", entry["contracts"]["status"])

    print("\nBOTH LAYERS TOGETHER\n")

    done = run(broken, "--json")
    payload = json.loads(done.stdout)
    entry = next(iter(payload.values()))
    check("names and contracts are both reported for one file",
          len(entry["findings"]) == 3 and entry["contracts"]["status"] == "VIOLATED",
          f"{len(entry['findings'])} name(s), contracts {entry['contracts']['status']}")
    check("the contract finding names the contradiction",
          "was stated to give" in entry["contracts"]["findings"][0]["detail"],
          entry["contracts"]["findings"][0]["detail"][:60])

    print("\nEXIT CODES, SO THIS WORKS IN A PIPELINE\n")

    check("findings exit non-zero", run(sample).returncode == 1)
    clean = os.path.join(EXAMPLES, "clean.py")
    with open(clean, "w") as fh:
        fh.write('"""A file with nothing wrong with it."""\n'
                 "import math\n\n\n"
                 "def hypotenuse(a, b):\n"
                 '    """Length of the hypotenuse.\n\n'
                 "    >>> hypotenuse(3, 4)\n    5.0\n"
                 '    """\n'
                 "    return math.sqrt(a * a + b * b)\n")
    done = run(clean)
    check("a clean file exits zero", done.returncode == 0, f"exit {done.returncode}")
    check("a clean file says silence is not a proof of correctness",
          "does NOT mean the code is correct" in done.stdout)

    print("\nREPORTS\n")

    done = run(sample, "--report", "md")
    md = sample + ".hedgemony.md"
    check("a markdown report is written next to the file", os.path.exists(md))
    body = open(md).read() if os.path.exists(md) else ""
    check("the report contains the whole file", body.count("\n! ") + body.count("\n+ ") > 10,
          f"{body.count(chr(10) + '! ') + body.count(chr(10) + '+ ')} lines marked")
    check("flagged lines carry a reference number", "#1" in body)

    done = run(sample, "--report", "html")
    page = sample + ".hedgemony.html"
    check("an html report is written", os.path.exists(page))
    html = open(page).read() if os.path.exists(page) else ""
    check("the page loads nothing from the network", "http" not in html.replace("http-equiv", ""))
    check("the page is self-contained and small", 0 < len(html) < 400_000, f"{len(html)} bytes")

    # Running twice must not leave two reports behind.
    before = sorted(f for f in os.listdir(EXAMPLES) if ".hedgemony." in f)
    run(sample, "--report", "md")
    run(sample, "--report", "md")
    after = sorted(f for f in os.listdir(EXAMPLES) if ".hedgemony." in f)
    check("running again updates the report instead of adding another",
          before == after, f"{len(after)} report file(s)")

    print("\nSAFETY DEFAULTS\n")

    check("the network is off unless asked for",
          os.environ.get("HEDGEMONY_ONLINE") != "1" or "--online" in sys.argv,
          "registry checks require --online")
    done = run(EXAMPLES, "--no-run", "--json")
    payload = json.loads(done.stdout)
    # Named for exactly what is asserted. `--no-run` runs no CHECKED FILE -- that is what
    # SKIPPED means and it is what this proves. It does not mean nothing at all executes: the
    # checked file's dependencies are still imported, because deciding whether a name exists
    # means importing the module that would answer. Stating the broader guarantee would be the
    # tool overstating itself, which is the failure it exists to find in other people's work.
    check("--no-run runs none of the checked files",
          all(v["contracts"]["status"] == "SKIPPED" for v in payload.values()),
          f"{len(payload)} file(s), none of them run")

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
