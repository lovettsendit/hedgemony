"""Every defect an external audit found before 1.0.0, held down by a test.

WHY THIS FILE EXISTS SEPARATELY. Nine suites and two hundred checks passed while all seven of
these were live. That is the useful fact: a green suite proves the cases someone thought of,
and these are the ones nobody had. Each test below states the defect it descends from, so a
later reader can tell what it is protecting rather than guessing from an assertion.

TWO OF THEM ARE FALSE ALARMS, and those are the serious ones. A missed fabrication still meets
every test and review downstream. A false alarm rewrites correct code, and the person acting on
it has no way to discover the tool was wrong.
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from hedgemony import resolve                                    # noqa: E402
from hedgemony.contracts import check_contracts                  # noqa: E402
from hedgemony.scan import scan, scan_python                     # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  [{'ok  ' if condition else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def write(body, name="probe.py", directory=None):
    directory = directory or tempfile.mkdtemp(prefix="hedgemony-reg-")
    path = os.path.join(directory, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(textwrap.dedent(body).lstrip("\n"))
    return path


def main():
    print("\nREGRESSIONS -- one per audit finding, each stating what it protects\n")

    # ------------------------------------------------------------------ 2. FALSE ALARM
    # Examples in a docstring build on each other. Each example was being given its own copy of
    # the namespace, so `value` did not survive to the next line and correct code was reported
    # as a broken contract. The most ordinary shape a doctest has.
    path = write('''
        def add_one(x):
            """Add one to a number.

            >>> value = 2
            >>> add_one(value)
            3
            """
            return x + 1
        ''')
    result = check_contracts(path)
    check("examples in one docstring share a namespace, as doctest has always worked",
          result.status == "OK" and result.examples == 2 and not result.findings,
          f"status={result.status} examples={result.examples}")

    # The namespace being shared must not blunt the check itself.
    path = write('''
        def add_one(x):
            """Add one to a number.

            >>> value = 2
            >>> add_one(value)
            99
            """
            return x + 1
        ''')
    result = check_contracts(path)
    check("and a genuinely violated example in that same shape is still caught",
          result.status == "VIOLATED" and len(result.findings) == 1,
          f"status={result.status}")

    # ------------------------------------------------------------------ 4. MISSED FABRICATION
    # Import bindings were matched with a regular expression, which cannot see that
    # `import json as js` binds `js`. The receiver went unresolved, so the file was reported
    # clean -- silently, with no indication anything had been skipped.
    findings, _ = scan_python("import json as js\n\ndata = js.serialise({'x': 1})\n")
    check("an aliased module import is resolved, not skipped",
          any(f["kind"] == "ATTR" and f["token"] == "js.serialise" for f in findings),
          f"found {[f['token'] for f in findings] or 'nothing'}")

    findings, _ = scan_python("import json as js\n\ndata = js.dumps({'x': 1})\n")
    check("and a correct call through the same alias raises no finding",
          not findings, "no false alarm on the negative control")

    # `from X import Y as Z` binds Z to X.Y. Both halves of that have to be right.
    findings, _ = scan_python("from json import dumps as write\n\nwrite({'x': 1})\n")
    check("an aliased `from` import resolves to the real object",
          not findings, "no false alarm on a renamed import")

    bindings = resolve.import_bindings(
        "import json as js\nimport os.path\nfrom json import dumps as write\n")
    check("the binding table is built from the grammar, not from pattern matching",
          bindings.get("js") == ("module", "json", "json")
          and bindings.get("os") == ("module", "os", "os.path")
          and bindings.get("write") == ("attr", "json", "dumps"),
          "alias, dotted import and renamed from-import all bind correctly")

    # ------------------------------------------------------------------ 3. FALSE ALARM
    # A submodule that exists but raises on import -- because an optional dependency of its own
    # is absent -- was reported as a submodule that does not exist. Real code, called imaginary.
    package = tempfile.mkdtemp(prefix="hedgemony-pkg-")
    write("", "realpkg/__init__.py", directory=package)
    write("import a_package_that_does_not_exist_at_all\n\nvalue = 1\n",
          "realpkg/sub.py", directory=package)
    sys.path.insert(0, package)
    try:
        findings, unchecked = scan_python("from realpkg.sub import value\n")
    finally:
        sys.path.remove(package)
        for module in [m for m in sys.modules if m.startswith("realpkg")]:
            del sys.modules[module]
    check("a real submodule whose own import fails is not called nonexistent",
          not any(f["kind"] == "MODPATH" for f in findings),
          f"reported {[f['kind'] for f in findings] or 'nothing'}")
    check("it is reported as unexamined instead, so the gap is visible",
          "realpkg" in unchecked, f"unchecked={sorted(unchecked)}")

    # An actually-absent submodule must still be caught, or the fix above would be a hole.
    sys.path.insert(0, package)
    try:
        findings, _ = scan_python("from realpkg.nosuchthing import value\n")
    finally:
        sys.path.remove(package)
        for module in [m for m in sys.modules if m.startswith("realpkg")]:
            del sys.modules[module]
    check("while a submodule that genuinely does not exist is still caught",
          any(f["kind"] == "MODPATH" for f in findings),
          f"reported {[f['kind'] for f in findings] or 'nothing'}")

    # ------------------------------------------------------------------ 5. WRONG ENVIRONMENT
    # The board never received the chosen interpreter, so it always scored against hedgemony's
    # own. A project whose libraries were invisible ranked clean for that reason.
    from hedgemony.board import rank
    import inspect
    parameters = inspect.signature(rank).parameters
    check("the board accepts the interpreter and the scans done in it",
          "interpreter" in parameters and "scans" in parameters,
          "so a board cannot silently score the wrong environment")

    directory = tempfile.mkdtemp(prefix="hedgemony-board-")
    target = write("import json\n\nvalue = json.dumps({})\n", "sample.py", directory=directory)
    supplied = {target: {"language": "python", "lines": 2, "rate": 50.0,
                         "unchecked_imports": [],
                         "findings": [{"line": 1, "kind": "ATTR", "token": "json.nope",
                                       "detail": "`json` has no attribute `nope`"}]}}
    sources = rank([directory], run_contracts=False, scans=supplied)
    check("and results already obtained there are the ones it scores",
          sources and sources[0].fabrications == 1,
          f"scored {sources[0].fabrications if sources else '?'} from the supplied scan")

    # ------------------------------------------------------------------ 1. HONEST WORDING
    # Asking the interpreter whether a name exists means importing the module that would answer,
    # and importing anything runs its top-level code. The checked file is not executed; its
    # dependencies are. Claiming "nothing executes" was an overstatement of exactly the kind
    # this tool exists to catch, so the claim is gone and this records why.
    marker = os.path.join(tempfile.mkdtemp(prefix="hedgemony-side-"), "ran.txt")
    package = tempfile.mkdtemp(prefix="hedgemony-side-pkg-")
    write(f"open({marker!r}, 'w').write('yes')\n\ndef work():\n    return 1\n",
          "sideeffect_probe.py", directory=package)
    sys.path.insert(0, package)
    try:
        scan_python("import sideeffect_probe\n\nsideeffect_probe.work()\n")
    finally:
        sys.path.remove(package)
        sys.modules.pop("sideeffect_probe", None)
    check("a dependency's import-time code does run, and the docs no longer deny it",
          os.path.exists(marker),
          "the checked file is parsed; what it imports is imported")

    # THE CLAIM IS CHECKED WHEREVER IT IS MADE, which includes this suite. A test name is read
    # by whoever runs it, so a check called "executes nothing" asserts that to its reader just
    # as a README paragraph does -- and two of them did, while asserting something narrower and
    # true. An overstatement in the thing that verifies is worse than one in the prose, because
    # it arrives stamped as verified.
    overstatements = ("guarantees nothing is executed", "executes nothing",
                      "never execute anything", "nothing is ever executed")
    # `._`-prefixed files are macOS AppleDouble sidecars, not source. On a filesystem with no
    # native metadata -- exFAT, FAT32, most network shares -- macOS writes one beside every
    # file, and they are binary, so reading one as text raises. The tool skips them by name
    # everywhere it gathers files; anything walking a directory here has to do the same.
    surfaces = [os.path.join(ROOT, d) for d in ("README.md", "AGENT.md", "SKILL.md")]
    surfaces += [os.path.join(HERE, f) for f in sorted(os.listdir(HERE))
                 if f.endswith(".py") and not f.startswith("._")
                 and f != os.path.basename(__file__)]
    for surface in surfaces:
        text = open(surface, encoding="utf-8").read().lower()
        found = [phrase for phrase in overstatements if phrase in text]
        check(f"{os.path.basename(surface)} does not overstate what --no-run prevents",
              not found, f"said {found}" if found else "claim matches the code")

    # ------------------------------------------------------------------ 7. BUILDABLE CLAIM
    # The SPDX licence field needs setuptools 77, and setuptools 77 needs Python 3.9. Declaring
    # 3.8 promised a source install that could never build its own build environment.
    config = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    check("the declared Python floor is one the build backend can actually meet",
          'requires-python = ">=3.9"' in config and "setuptools>=77" in config,
          "3.9 floor matches the setuptools 77 requirement")

    # ------------------------------------------------------------------ PUBLISHING HYGIENE
    # This project is edited on an exFAT volume, where macOS has nowhere to put a file's
    # metadata and so writes a hidden `._name` companion beside every single file. They are
    # binary, they match every source glob, and there are as many of them as there are files.
    # Committing them would push a shadow copy of the whole tree to a public repository, and
    # shipping them would put binary files inside the sdist. Both routes are closed by name,
    # and that is asserted here rather than assumed, because the cost of finding out later is
    # a public commit that cannot be taken back.
    ignore = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    check("the repository ignores macOS sidecars and folder metadata",
          "._*" in ignore and ".DS_Store" in ignore,
          "nothing macOS writes can be committed by name")

    manifest = open(os.path.join(ROOT, "MANIFEST.in"), encoding="utf-8").read()
    check("the source distribution excludes them too",
          "global-exclude ._*" in manifest and "global-exclude .DS_Store" in manifest,
          "a build on this volume cannot ship them either")

    present = []
    for base, directories, files in os.walk(ROOT):
        directories[:] = [d for d in directories if d not in {".git", "dist", "build"}
                          and not d.endswith(".egg-info")]
        present += [f for f in files if f.startswith("._") or f == ".DS_Store"]
    print(f"        note: {len(present)} sidecar file(s) present on this volume right now -- "
          f"ignored, never committed, never shipped")

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
