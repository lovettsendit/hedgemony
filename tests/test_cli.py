"""Every command, flag and path a person actually types.

The other suites test the parts. This one tests the product: what happens when someone points
it at a directory, asks for a report, pipes it to a script, or runs it with nothing installed
and no idea what it does.

Anything that would need the network is exercised without it -- the registry layer is checked
for the property that matters offline (it returns UNKNOWN rather than guessing), and the
non-Python ecosystems are driven with the registry stubbed, so the suite never depends on an
internet connection to pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from hedgemony import resolve                                 # noqa: E402
# `from hedgemony import scan` gives the FUNCTION -- the package re-exports it, shadowing the
# module of the same name. Submodule members are reached by importing them directly.
from hedgemony import scan as scan_function                   # noqa: E402
from hedgemony.scan import scan_other                         # noqa: E402
from hedgemony.report import report_path                      # noqa: E402


def flat(text):
    """Collapse whitespace so a check is about the words, not about where lines wrapped."""
    return " ".join(text.split())

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  [{'ok  ' if condition else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "hedgemony", *args], cwd=cwd,
                          capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def workspace():
    """A small project tree, including the things a real one has that must be skipped."""
    root = tempfile.mkdtemp(prefix="hedgemony-cli-")
    os.makedirs(os.path.join(root, "pkg"))
    os.makedirs(os.path.join(root, "pkg", "__pycache__"))
    os.makedirs(os.path.join(root, "node_modules"))
    os.makedirs(os.path.join(root, ".git"))

    with open(os.path.join(root, "pkg", "good.py"), "w") as fh:
        fh.write("import math\n\n\ndef area(r):\n"
                 '    """Area of a circle.\n\n    >>> round(area(1), 2)\n    3.14\n    """\n'
                 "    return math.pi * r * r\n")
    with open(os.path.join(root, "pkg", "bad.py"), "w") as fh:
        fh.write("import math\n\n\ndef middle(xs):\n    return math.median(xs)\n")
    # Files under here must never be checked.
    for junk in (("pkg", "__pycache__", "cached.py"), ("node_modules", "dep.py"),
                 (".git", "hook.py")):
        with open(os.path.join(root, *junk), "w") as fh:
            fh.write("import math\nmath.median([1])\n")
    return root


def main():
    print("\nFIRST CONTACT -- what someone types before reading anything\n")

    done = run("--version")
    check("--version prints a version", done.returncode == 0 and "hedgemony" in done.stdout,
          done.stdout.strip())

    done = run("--help")
    check("--help explains what it is", done.returncode == 0 and "made up" in done.stdout)
    check("--help warns that clean is not correct",
          "not a proof" in done.stdout or "not a proof" in done.stdout.lower())

    done = run("/no/such/path/anywhere.py")
    check("a path that does not exist exits 2, not 0", done.returncode == 2,
          f"exit {done.returncode}")

    print("\nA DIRECTORY, THE WAY PEOPLE ACTUALLY POINT IT\n")

    root = workspace()
    done = run(root, "--json")
    payload = json.loads(done.stdout)
    names = sorted(os.path.basename(p) for p in payload)
    check("both real source files are found", names == ["bad.py", "good.py"], ", ".join(names))
    check("__pycache__, node_modules and .git are skipped",
          not any(x in p for p in payload for x in ("__pycache__", "node_modules", ".git")))

    bad = next(v for k, v in payload.items() if k.endswith("bad.py"))
    good = next(v for k, v in payload.items() if k.endswith("good.py"))
    check("the broken file is flagged", len(bad["findings"]) == 1, bad["findings"][0]["detail"])
    check("the correct file is not flagged", not good["findings"])
    check("a correct file's stated example is checked and holds",
          good["contracts"]["status"] == "OK", good["contracts"]["status"])
    check("a file with no examples reports NO_CONTRACT",
          bad["contracts"]["status"] == "NO_CONTRACT", bad["contracts"]["status"])

    done = run(root)
    check("a multi-file run prints a total", "TOTAL" in done.stdout)
    check("findings exit 1", done.returncode == 1)

    done = run(root, "--quiet")
    check("--quiet hides the clean file", "good.py" not in done.stdout and
          "bad.py" in done.stdout)

    print("\nOUTPUT A SCRIPT CAN READ\n")

    check("--json emits nothing but JSON", isinstance(payload, dict) and payload)
    entry = bad
    for field in ("language", "lines", "rate", "findings", "contracts"):
        check(f"--json includes `{field}`", field in entry)
    for field in ("status", "examples", "findings", "error"):
        check(f"--json contract block includes `{field}`", field in entry["contracts"])
    finding = entry["findings"][0]
    for field in ("line", "kind", "token", "detail"):
        check(f"--json finding includes `{field}`", field in finding)

    done = run(root, "--no-colour")
    check("--no-colour emits no escape codes", "\033[" not in done.stdout)

    print("\nREPORTS\n")

    target = os.path.join(root, "pkg", "bad.py")
    run(target, "--report", "md")
    md_path = report_path(target, "md")
    check("--report writes markdown to one fixed name", os.path.exists(md_path))
    body = open(md_path).read()
    check("the markdown carries every line of the source",
          all(f"| {t}" in body for t in ("import math", "def middle(xs):")))
    check("the flagged line is marked and numbered", "! " in body and "#1" in body)
    check("clean lines are marked too", "+ " in body)

    run(target, "--report", "html")
    html_path = report_path(target, "html")
    page = open(html_path).read()
    check("--report html writes a page", os.path.exists(html_path))
    check("the page is black-grounded", "background:#000" in page.replace(" ", ""))
    check("the page colours clean and flagged lines differently",
          "tr.ok td.t" in page and "tr.hit td.t" in page)
    check("the page loads nothing external",
          "http://" not in page and "https://" not in page)
    check("the page says a clean scan is not a proof of correctness",
          "not a proof of correctness" in flat(page))

    before = sorted(os.listdir(os.path.dirname(md_path)))
    run(target, "--report", "md")
    run(target, "--report", "md")
    check("re-running updates the report rather than adding more",
          sorted(os.listdir(os.path.dirname(md_path))) == before)

    done = run(os.path.dirname(md_path), "--json")
    scanned = json.loads(done.stdout)
    check("its own reports are never treated as input",
          not any(".hedgemony." in p for p in scanned), f"{len(scanned)} file(s) checked")

    done = run(target, "--report", "both")
    check("--report both writes one of each",
          os.path.exists(report_path(target, "md"))
          and os.path.exists(report_path(target, "html")))

    # macOS writes a `._name` metadata companion for every file on exFAT, FAT32, SD cards and
    # most network shares. They end in `.py`, they are binary, and they are not source.
    sidecar = os.path.join(root, "pkg", "._bad.py")
    with open(sidecar, "wb") as fh:
        fh.write(b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X" + b"\x00" * 40)
    done = run(root, "--json")
    scanned = json.loads(done.stdout)
    check("macOS metadata sidecars are skipped when walking a directory",
          not any(os.path.basename(p).startswith("._") for p in scanned),
          f"{len(scanned)} file(s), none of them sidecars")
    done = run(sidecar, "--json")
    check("and skipped when one is named directly", done.returncode == 2,
          "reported as nothing to check rather than parsed as source")

    print("\nLIMITS AND SWITCHES\n")

    done = run(root, "--no-run", "--json")
    payload = json.loads(done.stdout)
    check("--no-run runs none of the checked files",
          all(v["contracts"]["status"] == "SKIPPED" for v in payload.values()),
          "SKIPPED on every file; their dependencies are still imported")

    slow = os.path.join(root, "pkg", "slow.py")
    with open(slow, "w") as fh:
        fh.write("import time\n\n\ndef f():\n"
                 '    """\n    >>> f()\n    1\n    """\n'
                 "    time.sleep(30)\n    return 1\n")
    done = run(slow, "--timeout", "3", "--json")
    payload = next(iter(json.loads(done.stdout).values()))
    check("--timeout is honoured and reported as UNCHECKED, not as a failure",
          payload["contracts"]["status"] == "UNCHECKED", payload["contracts"]["error"] or "")

    hog = os.path.join(root, "pkg", "hog.py")
    with open(hog, "w") as fh:
        fh.write("import time\n\nbuf = bytearray(200 * 1024 * 1024)\ntime.sleep(4)\n\n\n"
                 'def f():\n    """\n    >>> f()\n    1\n    """\n    return 1\n')
    done = run(hog, "--memory", "64", "--json")
    payload = next(iter(json.loads(done.stdout).values()))
    check("--memory is honoured and reported as UNCHECKED",
          payload["contracts"]["status"] == "UNCHECKED", payload["contracts"]["error"] or "")

    print("\nTHE REGISTRY LAYER, WITHOUT NEEDING A NETWORK\n")

    os.environ.pop("HEDGEMONY_ONLINE", None)
    check("offline, a registry lookup answers UNKNOWN rather than guessing",
          resolve.registry_has("anything-at-all", "python") is None)

    os.environ["HEDGEMONY_ONLINE"] = "1"
    check("a package name that could not be a real name is refused before any request",
          resolve.registry_has("not a package name!", "python") is None,
          "arbitrary text never reaches a URL")
    os.environ.pop("HEDGEMONY_ONLINE", None)

    # The non-Python ecosystems are driven with the registry answer supplied directly, so the
    # extraction and the standard-library exclusions are covered with no connection.
    saved = resolve.registry_has
    try:
        resolve.registry_has = lambda pkg, eco="python": False
        rust = scan_other("use serde::Serialize;\nuse std::fmt;\n", "rust")
        check("rust: a crate is extracted and the standard library is excluded",
              [f["token"] for f in rust] == ["serde"], str([f["token"] for f in rust]))
        js = scan_other("const x = require('leftpad');\nconst y = require('fs');\n",
                                    "js")
        check("javascript: a package is extracted and built-ins are excluded",
              [f["token"] for f in js] == ["leftpad"], str([f["token"] for f in js]))
        go = scan_other('import (\n\t"github.com/x/y"\n\t"fmt"\n)\n', "go")
        check("go: an import path is extracted and the standard library is excluded",
              [f["token"] for f in go] == ["github.com"], str([f["token"] for f in go]))
    finally:
        resolve.registry_has = saved

    rust_file = os.path.join(root, "lib.rs")
    with open(rust_file, "w") as fh:
        fh.write("use serde::Serialize;\n")
    done = run(rust_file, "--json")
    entry = next(iter(json.loads(done.stdout).values()))
    check("a rust file is recognised and reported as rust",
          entry["language"] == "rust", entry["language"])
    check("offline, a rust file yields no findings rather than false ones",
          not entry["findings"])

    print("\nAWKWARD INPUT\n")

    broken = os.path.join(root, "pkg", "syntax.py")
    with open(broken, "w") as fh:
        fh.write("def nope(:\n")
    done = run(broken)
    check("a file that will not parse does not crash the tool", done.returncode in (0, 1),
          f"exit {done.returncode}")

    empty = os.path.join(root, "pkg", "empty.py")
    open(empty, "w").close()
    done = run(empty)
    check("an empty file is handled", done.returncode == 0)

    unicode_file = os.path.join(root, "pkg", "unicode.py")
    with open(unicode_file, "w", encoding="utf-8") as fh:
        fh.write('# comment with an em dash — and emoji 🎯\nimport math\n'
                 "print(math.median([1]))\n")
    done = run(unicode_file, "--json")
    entry = next(iter(json.loads(done.stdout).values()))
    check("a file with non-ascii characters is scanned normally",
          len(entry["findings"]) == 1, entry["findings"][0]["detail"])

    run(unicode_file, "--report", "html")
    page = open(report_path(unicode_file, "html"), encoding="utf-8").read()
    check("non-ascii survives into the html report", "—" in page and "🎯" in page)

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
