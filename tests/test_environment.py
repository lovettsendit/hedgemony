"""Can this tool check code that lives in a different environment than it does?

WHY THIS MATTERS MORE THAN IT SOUNDS. Every verdict comes from asking an interpreter whether a
name exists, so which interpreter is asked decides the answer. Installed on its own -- a tool
venv, pipx, a global install -- this cannot see the libraries the code under test imports, and
correctly reports nothing about them. Nothing is the honest answer and it reads exactly like a
pass.

So the scan is handed to the interpreter that owns the code. This suite builds two environments
that genuinely differ and checks the handover happens, that it changes the result, and that
when it does not happen the gap is stated out loud instead of being passed over.

Building a virtual environment takes a few seconds, which is why this is its own suite.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import venv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from hedgemony.environment import (RemoteScanner, find_interpreter,          # noqa: E402
                                   is_same_environment)

PASS, FAIL = [], []

# `rich` is not imported by this suite; it is only ever named inside the sample below and asked
# about through an interpreter, so the suite works whether or not it is installed here.
SAMPLE = ("from rich.console import Console\n"
          "console = Console()\n"
          "console.table('a', 'b')\n"
          "console.print('hello')\n")


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  [{'ok  ' if condition else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def main():
    print("\nFINDING THE RIGHT INTERPRETER\n")

    root = tempfile.mkdtemp(prefix="hedgemony-env-test-")
    project = os.path.join(root, "project")
    os.makedirs(os.path.join(project, "src"))
    target = os.path.join(project, "src", "app.py")
    with open(target, "w") as fh:
        fh.write(SAMPLE)

    check("with no environment anywhere, the current interpreter is used",
          find_interpreter(None, near=target) == sys.executable)

    print("  building a virtual environment for the project (a few seconds)...")
    env_dir = os.path.join(project, ".venv")
    venv.create(env_dir, with_pip=True)
    project_python = os.path.join(env_dir, "bin", "python")
    if not os.path.isfile(project_python):
        project_python = os.path.join(env_dir, "Scripts", "python.exe")

    found = find_interpreter(None, near=target)
    check("a virtual environment beside the code is found from a nested file",
          os.path.dirname(found) == os.path.dirname(project_python),
          "walked up from src/app.py to the project root")

    check("an explicit interpreter beats everything",
          find_interpreter(sys.executable, near=target) == sys.executable)

    try:
        find_interpreter("/definitely/not/an/interpreter")
        raised = False
    except FileNotFoundError:
        raised = True
    check("a bad --python is refused rather than silently ignored", raised)

    print("\nTHE COMPARISON THAT DECIDES WHETHER TO HAND OVER\n")

    # THE BUG THIS PINS. A virtual environment's `python` is normally a symlink to the base
    # installation, so two environments with completely different packages resolve to one
    # identical path. Comparing the executable called them the same and skipped the handover,
    # and the scan then ran without the project's libraries and reported nothing.
    # Whether these two resolve to one binary depends on how the environment was created, so
    # it is reported rather than asserted. The assertion below is the one that matters: the
    # environments must be seen as different however their executables happen to resolve.
    same_binary = os.path.realpath(project_python) == os.path.realpath(sys.executable)
    print(f"    the two executables resolve to the same file: {same_binary}"
          + ("   <- comparing binaries here would have been wrong" if same_binary else ""))
    check("two environments with different packages are recognised as different",
          not is_same_environment(project_python), "compared by sys.prefix, not by binary")
    check("the current interpreter is recognised as itself",
          is_same_environment(sys.executable))

    print("\nDOES THE HANDOVER CHANGE THE ANSWER?\n")

    with RemoteScanner(project_python) as scanner:
        before = scanner.scan_files([target])[target]
    check("without the library, nothing is decided about it",
          not before["findings"] and "rich" in before.get("unchecked_imports", []),
          "reported as NOT CHECKED, not as clean")

    print("  installing a library into the project environment (a few seconds)...")
    subprocess.run([project_python, "-m", "pip", "install", "-q", "rich"],
                   capture_output=True, timeout=300)

    with RemoteScanner(project_python) as scanner:
        after = scanner.scan_files([target])[target]
    flagged = {f["token"] for f in after["findings"]}
    check("with the library, the invented method is caught",
          "console.table" in flagged, ", ".join(sorted(flagged)) or "nothing")
    check("and the real method on the same object is not",
          "console.print" not in flagged)
    check("nothing is left unchecked once the library is present",
          not after.get("unchecked_imports"), "every import resolved")

    print("\nTHE HANDOVER DOES NOT LEAK THIS TOOL'S OWN ENVIRONMENT\n")

    # Putting this package's site-packages on the target's path would let the target resolve
    # names against libraries it does not really have -- silent false negatives. Only a copy of
    # this package is staged, so a library installed beside it stays invisible.
    with RemoteScanner(project_python) as scanner:
        staged = sorted(os.listdir(scanner._staging))
    check("only this package is staged for the other interpreter",
          staged == ["hedgemony"], str(staged))

    print("\nTHROUGH THE COMMAND LINE\n")

    done = subprocess.run([sys.executable, "-m", "hedgemony", target,
                           "--python", project_python, "--json"],
                          cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    entry = next(iter(json.loads(done.stdout).values()))
    check("--python routes the scan to the named interpreter",
          any(f["token"] == "console.table" for f in entry["findings"]),
          f"{len(entry['findings'])} finding(s)")
    check("--json carries the unchecked imports field",
          "unchecked_imports" in entry)

    done = subprocess.run([sys.executable, "-m", "hedgemony", target,
                           "--python", project_python, "--no-colour"],
                          cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    check("the interpreter actually used is stated in the output",
          "using the interpreter that owns this code" in done.stdout)

    print("\nAN INTERPRETER THAT CANNOT RUN THE SCAN\n")

    # An interpreter can be present, be a real Python, and still be unable to run this -- too
    # old for the syntax, missing a module, or a shim that is not an interpreter at all.
    # Discovering that per file produced an error per file and NO results, which is worse than
    # never handing over: the reader got nothing instead of the partial answer available here.
    shim = os.path.join(root, "notpython")
    with open(shim, "w") as fh:
        fh.write("#!/bin/sh\n"
                 'if [ "$1" = "-c" ]; then echo "/fake/prefix"; echo "2.7.18"; exit 0; fi\n'
                 'echo "SyntaxError: invalid syntax" >&2; exit 1\n')
    os.chmod(shim, 0o755)

    with RemoteScanner(shim) as scanner:
        works, why = scanner.usable()
    check("an interpreter that cannot run the scan is detected before any work",
          not works, why[:60])

    with RemoteScanner(sys.executable) as scanner:
        works, _why = scanner.usable()
    check("a working interpreter is accepted", works)

    example = os.path.join(ROOT, "examples", "broken.py")
    done = subprocess.run([sys.executable, "-m", "hedgemony", example,
                           "--python", shim, "--no-colour"],
                          cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    check("it falls back and still produces a full result",
          "CONTRACT" in done.stdout and "ATTR" in done.stdout,
          "a partial answer beats no answer")
    check("and says why it fell back rather than doing it silently",
          "cannot run the scan" in done.stderr and "NOT CHECKED" in done.stderr)
    check("the exit code still reports findings, so a pipeline is not misled",
          done.returncode == 1, f"exit {done.returncode}")

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
