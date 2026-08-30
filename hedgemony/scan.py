"""Six kinds of fabrication, each decided by the interpreter or a package registry.

A FABRICATION IS A CLAIM ABOUT THE WORLD THAT IS FALSE. Not code that is ugly, not code that is
slow, not code a reviewer would write differently -- code that refers to something which does
not exist. Every class below is decidable, which is the whole reason this tool can report a
fact instead of a score:

    PACKAGE   import ghostlib            no such package was ever published
    MODPATH   from a.b import C          `a` is real, `a.b` is not
    IMPORT    from json import serialise `json` exists and does not export that
    ATTR      client.table(...)          the receiver has no such attribute
    KWARG     re.sub(..., greedy=True)   the function accepts no such keyword
    ARITY     sqrt(2, 3)                 the function cannot take that many arguments

WHAT THE CLASSES MEAN FOR WHOEVER READS THEM. They split into two actions, and the split is the
useful part:

    PACKAGE MODPATH IMPORT ATTR   the thing does not exist          -> rewrite
    KWARG ARITY                   the function is right, the call   -> fix the call
                                  is wrong

SILENCE IS NOT A PASS. Nothing here inspects behaviour. A file that scores zero can still be
completely wrong -- a correct call to the wrong function is invisible to every check in this
module, by construction. That is what contract checking is for, and the report says so rather
than letting a clean scan read as an endorsement.

WHAT DOES RUN, STATED PLAINLY. The checked file is never executed here; it is parsed. But
asking an interpreter whether `json` exports `serialise` means importing `json`, and importing
any module runs that module's top-level code. So the DEPENDENCIES named by the checked file are
imported, and a dependency with side effects at import time will perform them. This is the
price of asking the interpreter instead of guessing from a stub, and it is the reason every
verdict here is a fact -- but it is not "nothing executes", and claiming that would be the kind
of overstatement this tool exists to catch.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import os
import re

from . import resolve

__all__ = ["scan", "scan_python", "scan_other", "FabricationClass", "LANGUAGE_BY_SUFFIX"]


class FabricationClass:
    """The six classes, and what a reader should do about each."""

    PACKAGE = "PACKAGE"
    MODPATH = "MODPATH"
    IMPORT = "IMPORT"
    ATTR = "ATTR"
    KWARG = "KWARG"
    ARITY = "ARITY"
    # Not produced by this module. It is named here so that every class has exactly one
    # description, and readers of a report never meet a kind with no explanation.
    CONTRACT = "CONTRACT"

    REWRITE = (PACKAGE, MODPATH, IMPORT, ATTR)
    FIX_CALL = (KWARG, ARITY)

    ACTION = {
        PACKAGE: "rewrite -- no such package exists",
        MODPATH: "rewrite -- that submodule does not exist",
        IMPORT: "rewrite -- that name is not exported",
        ATTR: "rewrite -- that attribute does not exist",
        KWARG: "fix the call -- the function is real, the keyword is not",
        ARITY: "fix the call -- the function is real, the argument count is not",
        # Deliberately does not say which side to change. The file states one thing and does
        # another; the tool knows they disagree and does not know which one was intended.
        CONTRACT: "the code and its stated example disagree -- decide which one is wrong",
    }


LANGUAGE_BY_SUFFIX = {".py": "python", ".rs": "rust", ".js": "js", ".mjs": "js",
                      ".ts": "js", ".tsx": "js", ".jsx": "js", ".go": "go"}


def _spec_exists(dotted: str) -> bool:
    """Is there a module at this path, whether or not importing it succeeds?

    THE DISTINCTION THAT PREVENTS A FALSE ALARM. A submodule that exists on disk but raises on
    import -- because an optional dependency of its OWN is missing -- is not a fabrication. An
    earlier version could not tell the two apart and reported real, present code as a
    nonexistent submodule, which is precisely the failure this tool must never have: the person
    acting on it rewrites correct code and has no way to discover the tool was wrong.
    """
    try:
        return importlib.util.find_spec(dotted) is not None
    except Exception:                    # noqa: BLE001  find_spec imports parents; it can raise
        return False


def _callable_for(source: str, owner, name, bindings=None):
    """The function object behind `owner.name`, when it can be resolved without guessing."""
    try:
        if bindings is None:
            bindings = resolve.import_bindings(source)
        if owner is None:
            entry = bindings.get(name)
            return resolve.binding_object(bindings, name) if entry else None
        base = resolve.local_binding(source, owner) or owner
        obj = resolve.binding_object(bindings, base.split(".")[0])
        if obj is None:
            return None
        for part in base.split(".")[1:]:
            obj = getattr(obj, part)
        return getattr(obj, name, None)
    except Exception:                    # noqa: BLE001  unresolvable -> no finding
        return None


def _scan_imports(tree, findings, unchecked):
    """PACKAGE, MODPATH and IMPORT -- everything decidable from an import statement.

    `unchecked` collects packages that are not installed in the environment this is running
    in. Nothing about them can be decided -- their contents cannot be asked of an interpreter
    that does not have them -- so every name reached through one goes unexamined. That is
    reported rather than passed over, because a scan that is silent for a reason the reader
    cannot see is worse than one that found nothing.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                try:
                    importlib.import_module(alias.name)
                except ImportError:
                    if _spec_exists(alias.name):
                        # The module is there; its own import failed. Nothing about it is
                        # decidable, and it is certainly not invented.
                        unchecked.add(root)
                    elif resolve.registry_has(root, "python") is False:
                        findings.append({"line": node.lineno, "kind": FabricationClass.PACKAGE,
                                         "token": root,
                                         "detail": f"no package `{root}` was ever published"})
                    elif "." in alias.name and _spec_exists(root):
                        findings.append({"line": node.lineno, "kind": FabricationClass.MODPATH,
                                         "token": alias.name,
                                         "detail": f"`{root}` has no submodule `{alias.name}`"})
                    else:
                        unchecked.add(root)
                except Exception:        # noqa: BLE001  a module that raises on import
                    unchecked.add(root)

        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            root = node.module.split(".")[0]
            try:
                module = importlib.import_module(node.module)
            except ImportError:
                if _spec_exists(node.module):
                    # Present on disk, but it would not load -- an optional dependency of its
                    # own is missing. Real code, unexaminable, and not a fabrication.
                    unchecked.add(root)
                elif _spec_exists(root):
                    findings.append({"line": node.lineno, "kind": FabricationClass.MODPATH,
                                     "token": node.module,
                                     "detail": f"`{root}` has no submodule `{node.module}`"})
                elif resolve.registry_has(root, "python") is False:
                    findings.append({"line": node.lineno, "kind": FabricationClass.PACKAGE,
                                     "token": root,
                                     "detail": f"no package `{root}` was ever published"})
                else:
                    unchecked.add(root)
                continue
            except Exception:            # noqa: BLE001
                unchecked.add(root)
                continue
            for alias in node.names:
                if alias.name != "*" and not hasattr(module, alias.name):
                    findings.append({"line": node.lineno, "kind": FabricationClass.IMPORT,
                                     "token": alias.name,
                                     "detail": f"`{node.module}` does not export "
                                               f"`{alias.name}`"})


def _scan_calls(source, tree, findings):
    """ATTR, KWARG and ARITY -- everything decidable at a call site."""
    lines = source.splitlines()
    bindings = resolve.import_bindings(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        owner = name = None

        if isinstance(func, ast.Attribute):
            name = func.attr
            owner = (func.value.id if isinstance(func.value, ast.Name)
                     else ast.unparse(func.value) if hasattr(ast, "unparse") else None)
            if owner and re.fullmatch(r"[\w.]+", owner):
                point = {"line": node.lineno, "kind": "attr", "token": name}
                line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                if (f"{owner}.{name}" in line
                        and resolve.resolve_exists(source, point, "python") is False):
                    findings.append({"line": node.lineno, "kind": FabricationClass.ATTR,
                                     "token": f"{owner}.{name}",
                                     "detail": f"`{owner}` has no attribute `{name}`"})
                    continue
        elif isinstance(func, ast.Name):
            name = func.id
        if not name:
            continue

        target = _callable_for(source, owner, name, bindings)
        if target is None or inspect.isclass(target):
            continue
        try:
            signature = inspect.signature(target)
        except (ValueError, TypeError):
            # Builtins written in C often have no introspectable signature. Nothing can be
            # decided, so nothing is reported -- an unknown must never become a finding.
            continue

        parameters = signature.parameters
        takes_any_keyword = any(p.kind == p.VAR_KEYWORD for p in parameters.values())
        takes_any_positional = any(p.kind == p.VAR_POSITIONAL for p in parameters.values())

        for keyword in node.keywords:
            if keyword.arg and not takes_any_keyword and keyword.arg not in parameters:
                findings.append({"line": node.lineno, "kind": FabricationClass.KWARG,
                                 "token": f"{name}({keyword.arg}=)",
                                 "detail": f"`{name}` accepts no keyword `{keyword.arg}`"})

        if not takes_any_positional:
            allowed = sum(1 for p in parameters.values()
                          if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
            given = len(node.args)
            if given > allowed:
                findings.append({"line": node.lineno, "kind": FabricationClass.ARITY,
                                 "token": f"{name}/{given}",
                                 "detail": f"`{name}` takes at most {allowed} positional "
                                           f"argument(s), {given} given"})


def scan_python(source: str):
    """Every fabrication class this file can be checked for. The file itself is not executed.

    Its dependencies are imported, because that is what asking the interpreter costs -- see the
    module docstring. Returns the findings and the set of packages that could not be checked
    because they are not installed in the interpreter running this.
    """
    findings, unchecked = [], set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return findings, unchecked
    _scan_imports(tree, findings, unchecked)
    _scan_calls(source, tree, findings)
    return findings, unchecked


# Package existence is the one class that generalises to a language without running its
# toolchain, so it is the only one claimed for these. A `use` or a `require` names a package,
# and whether that package was ever published is a fact about a registry.
DEPENDENCY_PATTERN = {
    "rust": re.compile(r"^\s*use\s+([a-z0-9_]+)::", re.M),
    "js": re.compile(r"""(?:require\(|from\s+)['"]([@\w./-]+)['"]""", re.M),
    "go": re.compile(r'^\s*"([\w./-]+)"\s*$', re.M),
}
STANDARD_LIBRARY = {
    "rust": {"std", "core", "alloc", "crate", "self", "super"},
    "js": {"fs", "path", "os", "http", "https", "util", "crypto", "events", "stream",
           "buffer", "url", "zlib", "child_process", "assert", "net", "readline"},
    "go": {"fmt", "os", "io", "net", "time", "strings", "errors", "sort", "math", "bytes",
           "bufio", "context", "encoding", "strconv", "sync", "regexp", "log"},
}


def scan_other(source: str, ecosystem: str):
    """Package existence for languages with no interpreter to ask. Requires opting in."""
    findings = []
    pattern = DEPENDENCY_PATTERN.get(ecosystem)
    if not pattern:
        return findings
    for match in pattern.finditer(source):
        package = match.group(1).split("/")[0]
        if package in STANDARD_LIBRARY.get(ecosystem, set()) or package.startswith("."):
            continue
        if resolve.registry_has(package, ecosystem) is False:
            findings.append({"line": source[: match.start()].count("\n") + 1,
                             "kind": FabricationClass.PACKAGE, "token": package,
                             "detail": f"no `{package}` in the {ecosystem} registry"})
    return findings


def scan(path_or_source, language=None, is_source=False):
    """Scan a file or a string. Returns findings, the line count, and the rate.

    The rate -- fabrications per hundred lines -- is what makes two files or two models
    comparable. A count on its own says nothing without knowing how much code produced it.
    """
    if is_source:
        source = path_or_source
        language = language or "python"
    else:
        with open(path_or_source, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        if language is None:
            suffix = os.path.splitext(path_or_source)[1].lower()
            language = LANGUAGE_BY_SUFFIX.get(suffix, "python")

    if language == "python":
        findings, unchecked = scan_python(source)
    else:
        findings, unchecked = scan_other(source, language), set()
    findings.sort(key=lambda f: (f["line"], f["kind"]))
    counted = sum(1 for line in source.splitlines() if line.strip())
    return {
        "language": language,
        "lines": counted,
        "findings": findings,
        "rate": (100.0 * len(findings) / counted) if counted else 0.0,
        # Packages this interpreter does not have. Everything reached through one is
        # unexamined, and saying so is the difference between "nothing was wrong" and
        # "nothing could be looked at".
        "unchecked_imports": sorted(unchecked),
    }
