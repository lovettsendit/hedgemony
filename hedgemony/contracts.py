"""Does the code do what it says it does?

THE GAP THIS FILLS. Every other check in this tool asks whether a name exists. That catches an
invented library and it catches a method nobody ever wrote, but it is blind to the far more
common failure: a real function, called correctly, doing the wrong thing.

    def pages_needed(items, per_page):
        '''How many pages are needed to show every item.

        >>> pages_needed(10, 3)
        4
        '''
        return math.floor(items / per_page)

`math.floor` exists. The call is well formed. Every static checker passes this file, and it is
wrong -- ten items at three per page needs four pages, and this returns three. The only thing
that decides it is running the example the author wrote.

WHERE THE AUTHORITY COMES FROM, and why it can be trusted. The example is not this tool's
opinion about what the function should do. It is a claim the author put in the file, in a
standard format, executable by design. Reporting that it does not hold is reporting a
contradiction between two things already in the file -- never a judgement about intent, and
never anything a model was asked about. That is what makes a finding here a fact.

WHAT THIS DELIBERATELY DOES NOT DO. It does not infer contracts, guess at intent, or ask a
model what a function was meant to return. A file with no stated examples gets NO_CONTRACT --
"nothing was claimed, so nothing can be checked" -- which is the honest answer and is reported
as its own state rather than being folded into a pass. Silence about behaviour is not evidence
of correctness, and the report says so in those words.

SAFETY. Checking this requires running the file, and the file was written by a machine. Nothing
is executed in this process: every run is handed to the sandbox, which bounds CPU, memory,
processes, file size and wall time, refuses network access, strips the environment, and works
in a directory that is deleted afterwards. See `sandbox.py` for what that does and does not
protect against.
"""
from __future__ import annotations

import ast
import os

from .sandbox import DEFAULT_LIMITS, Limits, run_isolated

__all__ = ["check_contracts", "has_contracts", "ContractResult"]


class ContractResult:
    """The outcome of checking one file's stated contracts.

    `status` is one of:

        OK            every stated example held
        VIOLATED      at least one example did not hold -- these are the findings
        NO_CONTRACT   the file states nothing checkable; behaviour is UNKNOWN, not fine
        UNCHECKED     the run could not complete (a limit stopped it, or the file would not
                      import) -- also UNKNOWN, and never reported as a pass

    The last two exist as separate states on purpose. Collapsing "nothing was claimed" or "the
    check could not run" into "no problems found" is how a checker ends up telling someone that
    unexamined code is clean.
    """

    __slots__ = ("status", "findings", "examples", "error", "path")

    def __init__(self, status, findings=None, examples=0, error=None, path=""):
        self.status = status
        self.findings = findings or []
        self.examples = examples
        self.error = error
        self.path = path

    @property
    def checked(self):
        return self.status in ("OK", "VIOLATED")

    def __repr__(self):
        return (f"ContractResult({self.status}, findings={len(self.findings)}, "
                f"examples={self.examples})")


def has_contracts(source: str) -> int:
    """How many stated examples the file contains, decided without running anything.

    Parsing rather than importing matters here: this is what lets the tool tell someone that a
    file has nothing to check WITHOUT ever executing it. A file with no contracts is never run
    at all, so the safest possible answer costs nothing.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node)
            if doc:
                total += sum(1 for line in doc.splitlines() if line.strip().startswith(">>>"))
    return total


def check_contracts(path: str, limits: Limits = None,
                    interpreter: str = None) -> ContractResult:
    """Run every stated example in `path` under the sandbox and report what did not hold.

    `interpreter` names the Python the examples run under. An example that imports the
    project's own dependencies can only run in the environment that has them, so this follows
    whichever interpreter was chosen for the code under test.
    """
    path = os.path.abspath(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError as exc:
        return ContractResult("UNCHECKED", error=f"cannot read file: {exc}", path=path)

    stated = has_contracts(source)
    if stated == 0:
        # Nothing was claimed, so the file is never executed. This is the common case for
        # generated code, and it is worth reporting loudly rather than quietly passing.
        return ContractResult("NO_CONTRACT", examples=0, path=path)

    result = run_isolated(path, mode="contracts", limits=limits or DEFAULT_LIMITS,
                          interpreter=interpreter)

    if result.stopped:
        why = ("exceeded the memory limit" if result.over_memory else
               "exceeded the time limit" if result.timed_out else
               "was stopped by a resource limit")
        return ContractResult("UNCHECKED", error=f"the run {why}", path=path)

    payload = result.payload or {}
    if payload.get("error"):
        return ContractResult("UNCHECKED", error=payload["error"], path=path)
    if not result.ok:
        detail = (result.stderr or "").strip().splitlines()
        return ContractResult("UNCHECKED", path=path,
                              error=detail[-1][:200] if detail else "the run did not report")

    failures = payload.get("failures", [])
    findings = [{
        "line": f.get("line", 1),
        "kind": "CONTRACT",
        "token": f.get("name", ""),
        "detail": _describe(f),
    } for f in failures]
    return ContractResult("VIOLATED" if findings else "OK",
                          findings=findings, examples=payload.get("examples", stated), path=path)


def _describe(failure) -> str:
    """One line a reader can act on: what was claimed, and what happened instead."""
    statement = " ".join(failure.get("statement", "").split())
    expected = " ".join(failure.get("expected", "").split()) or "no output"
    got = _actual(failure.get("detail", ""))
    if got:
        return f"`{statement}` was stated to give `{expected}` but gave `{got}`"
    return f"`{statement}` was stated to give `{expected}` and did not"


def _actual(detail: str) -> str:
    """Pull what actually happened out of the runner's text, for a one-line summary.

    The full text is kept in the finding regardless; this only produces something short enough
    to sit on one line next to the code.
    """
    lines = [l.rstrip() for l in (detail or "").splitlines()]
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Got:":
            body = [l.strip() for l in lines[index + 1:] if l.strip()]
            return " ".join(body)[:120] if body else ""
        if stripped.startswith("Exception raised"):
            for tail in reversed(lines[index:]):
                if tail.strip() and not tail.startswith(" "):
                    continue
                if tail.strip() and ":" in tail:
                    return tail.strip()[:120]
            return "an exception"
    return ""
