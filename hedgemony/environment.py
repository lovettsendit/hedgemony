"""Ask the RIGHT interpreter, not merely the nearest one.

THE PROBLEM THIS SOLVES, and it is easy to be bitten by without noticing. Every verdict here
comes from asking an interpreter whether a name exists. Which interpreter therefore decides the
answer. Installed into its own environment -- `pipx install hedgemony`, a tool venv, a global
install -- this tool cannot see the packages the code under test actually imports, so it cannot
decide anything about them and correctly goes quiet:

    a clean venv        0 fabrications          <- nothing could be checked
    with the library    2 fabrications          <- same file, same tool

Silence that looks like a pass is the worst failure this tool can have. So rather than
demanding that people install it next to their code, it goes and asks their interpreter.

HOW. This package depends on nothing outside the standard library, which means any Python 3.8
or newer can run it. The package is copied to a temporary directory, that directory alone is
put on the target interpreter's path, and the scan runs there -- inside the environment that
owns the code, with that environment's packages resolvable.

WHY A COPY RATHER THAN THE INSTALLED LOCATION. Putting this package's own site-packages on the
target's path would expose everything else installed alongside it, and the target would resolve
names against libraries it does not really have. That would turn a checking tool into a source
of false negatives. The copy contains this package and nothing else.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

__all__ = ["find_interpreter", "RemoteScanner", "describe", "is_same_environment"]

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))

# Where a project keeps its interpreter, in the order people actually use.
VENV_NAMES = (".venv", "venv", ".env")
BIN = "Scripts" if os.name == "nt" else "bin"
EXE = "python.exe" if os.name == "nt" else "python"


def _interpreter_in(directory):
    candidate = os.path.join(directory, BIN, EXE)
    return candidate if os.path.isfile(candidate) else None


def find_interpreter(explicit=None, near=None):
    """Which interpreter should answer questions about this code?

    Explicit beats everything. Otherwise a virtual environment beside the code wins, then one
    the shell has activated, and finally the interpreter running this. Returning the current
    one is always a valid answer -- it is simply the case where no better environment was
    found.
    """
    if explicit:
        resolved = shutil.which(explicit) or explicit
        if not os.path.isfile(resolved):
            raise FileNotFoundError(f"no interpreter at {explicit}")
        return resolved

    if near:
        directory = os.path.abspath(near if os.path.isdir(near) else os.path.dirname(near))
        while True:
            for name in VENV_NAMES:
                found = _interpreter_in(os.path.join(directory, name))
                if found:
                    return found
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent

    active = os.environ.get("VIRTUAL_ENV")
    if active:
        found = _interpreter_in(active)
        if found:
            return found

    return sys.executable


def _prefix_of(interpreter):
    """The environment root an interpreter resolves to, or None if it cannot be asked."""
    try:
        done = subprocess.run([interpreter, "-c",
                               "import sys,platform;"
                               "print(sys.prefix);print(platform.python_version())"],
                              capture_output=True, text=True, timeout=15)
        lines = done.stdout.splitlines()
        return (lines[0].strip(), lines[1].strip()) if len(lines) >= 2 else None
    except Exception:                    # noqa: BLE001
        return None


def is_same_environment(interpreter):
    """Would this interpreter see the same packages as the one running now?

    COMPARING THE EXECUTABLE IS WRONG, and quietly so. A virtual environment's `python` is
    usually a symlink to the base installation, so two environments with entirely different
    site-packages resolve to one identical path:

        toolenv/bin/python  ->  /usr/local/bin/python3
        project/.venv/bin/python  ->  /usr/local/bin/python3

    A check on the resolved binary calls those the same interpreter and skips the handover,
    and the scan then runs without the project's libraries and reports nothing. What decides
    which packages are visible is `sys.prefix`, so that is what is compared.
    """
    other = _prefix_of(interpreter)
    if other is None:
        return False                     # cannot tell -- ask it directly rather than assume
    return os.path.normpath(other[0]) == os.path.normpath(sys.prefix)


def describe(interpreter):
    """A short, human-readable identification of an interpreter."""
    found = _prefix_of(interpreter)
    return f"Python {found[1]} at {found[0]}" if found else interpreter


_BOOTSTRAP = (
    "import json,sys\n"
    "from hedgemony.scan import scan\n"
    "out={}\n"
    "for p in sys.argv[1:]:\n"
    "    try: out[p]=scan(p)\n"
    "    except Exception as e: out[p]={'error':'%s: %s'%(type(e).__name__,e)}\n"
    "sys.stdout.write('__HEDGEMONY__'+json.dumps(out))\n"
)


class RemoteScanner:
    """Runs scans inside another interpreter. Reusable across many files.

    The package is copied once and every file goes through the same copy, because paying to
    stage it per file would make checking a directory slower than reading it.
    """

    def __init__(self, interpreter, online=False):
        self.interpreter = interpreter
        self.online = online
        self._staging = None

    def __enter__(self):
        self._staging = tempfile.mkdtemp(prefix="hedgemony-env-")
        shutil.copytree(PACKAGE_DIR, os.path.join(self._staging, "hedgemony"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*"))
        return self

    def __exit__(self, *_exc):
        if self._staging:
            shutil.rmtree(self._staging, ignore_errors=True)
        self._staging = None
        return False

    def usable(self):
        """Can this interpreter actually run the scan? Returns (True, "") or (False, reason).

        WHY THIS IS ASKED BEFORE ANY WORK. An interpreter can be present, be a perfectly good
        Python, and still be unable to run this -- too old for the syntax, built without a
        module this needs, wrapped in a shim that is not really an interpreter at all. Finding
        that out one file at a time produced an error per file and no results, which is worse
        than not handing over: the person gets nothing instead of the partial answer the local
        interpreter could have given. So it is settled once, up front, and a failure becomes a
        fallback rather than an outage.
        """
        if not self._staging:
            raise RuntimeError("RemoteScanner must be used as a context manager")
        try:
            done = subprocess.run(
                [self.interpreter, "-B", "-c", "import hedgemony.scan; print('ok')"],
                capture_output=True, text=True, timeout=60,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                     "PYTHONPATH": self._staging, "PYTHONDONTWRITEBYTECODE": "1"})
        except Exception as exc:         # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
        if "ok" in done.stdout:
            return True, ""
        detail = (done.stderr or "").strip().splitlines()
        return False, (detail[-1][:160] if detail else "it did not respond")

    def scan_files(self, paths, batch=40):
        """Scan every path and return {path: result}. Batched to bound the command length."""
        if not self._staging:
            raise RuntimeError("RemoteScanner must be used as a context manager")

        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", self._staging),
            "PYTHONPATH": self._staging,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if self.online:
            environment["HEDGEMONY_ONLINE"] = "1"

        results = {}
        for start in range(0, len(paths), batch):
            chunk = paths[start:start + batch]
            try:
                done = subprocess.run([self.interpreter, "-B", "-c", _BOOTSTRAP, *chunk],
                                      capture_output=True, text=True, timeout=300,
                                      env=environment)
            except Exception as exc:     # noqa: BLE001
                for path in chunk:
                    results[path] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            marker = done.stdout.rfind("__HEDGEMONY__")
            if marker < 0:
                detail = (done.stderr or "").strip().splitlines()
                for path in chunk:
                    results[path] = {"error": detail[-1][:200] if detail
                                     else "the interpreter returned nothing"}
                continue
            try:
                results.update(json.loads(done.stdout[marker + len("__HEDGEMONY__"):]))
            except ValueError:
                for path in chunk:
                    results[path] = {"error": "could not read the interpreter's reply"}
        return results
