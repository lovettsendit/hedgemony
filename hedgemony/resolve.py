"""Does this name exist? -- answered by the interpreter, never by a model.

Every verdict in this file comes from asking the running interpreter a direct question:
does `math.median` resolve? Does `json` export `serialise`? The answer is a fact about the
machine that will run the code, and it does not depend on how confident anything was.

THREE OUTCOMES, and the third is the important one. Every resolver returns True, False, or
None. `None` means the question could not be settled -- the package is not installed, the
receiver is a variable whose type is ambiguous, the language has no interpreter to ask -- and
it is reported as UNKNOWN, never quietly treated as fine.

That matters more than it looks. Reporting a real name as invented rewrites correct code, and
the person doing the rewriting has no way to discover the tool was wrong. A missed fabrication,
by contrast, still meets every test and review downstream. The costs are not symmetric, so
every ambiguous case resolves to silence.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import re

__all__ = ["module_has", "resolve_exists", "registry_has", "local_binding",
           "import_bindings", "binding_object"]

# Registry probes, used only to answer "was this package ever published?". Metadata is read;
# nothing is installed, downloaded to disk, or executed.
REGISTRY = {
    "python": "https://pypi.org/pypi/{}/json",
    "rust": "https://crates.io/api/v1/crates/{}",
    "js": "https://registry.npmjs.org/{}",
}


def _online() -> bool:
    return os.environ.get("HEDGEMONY_ONLINE") == "1"


def registry_has(package: str, ecosystem: str = "python"):
    """Was this package ever published? True, False, or None when it cannot be settled.

    NETWORK IS OFF BY DEFAULT, and the reason is specific rather than cautious in general: the
    name being looked up comes from generated code, so an invented package name would decide
    which address this machine contacts. Names that models invent do get registered by other
    people. A tool whose outbound requests are steered by unreviewed output should not make
    them without being asked, so this returns None until the person running it opts in.
    """
    if not _online() or ecosystem not in REGISTRY:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._@/-]{1,120}", package or ""):
        return None                      # never put an arbitrary string into a URL
    import urllib.request
    try:
        request = urllib.request.Request(REGISTRY[ecosystem].format(package),
                                         headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=6) as response:
            return response.status == 200
    except Exception as exc:             # noqa: BLE001
        # A 404 is an answer: no such package. Anything else -- offline, rate limited, a
        # timeout -- is not, and must not be read as absence.
        return False if getattr(exc, "code", None) == 404 else None


def module_has(module: str, attribute: str):
    """Does `module` export `attribute`? None when the module is not installed here.

    An uninstalled package is exactly where an invention is most likely to survive, because
    nothing local can contradict it. The honest answer is still UNKNOWN: settling it would
    mean fetching and reading the package's published source, and this tool does not download
    code in order to check code.
    """
    try:
        return hasattr(importlib.import_module(module), attribute)
    except ImportError:
        return None
    except Exception:                    # noqa: BLE001  a module that raises on import
        return None


def import_bindings(source: str):
    """Every local name an import statement binds, and what it binds to.

    WHY THE GRAMMAR AND NOT A REGULAR EXPRESSION. An import binds a name, and the bound name is
    very often not the imported one:

        import json as js                js -> the json module
        from json import dumps as write  write -> json.dumps
        import os.path                   os -> the os module, not `os.path`

    Matching `^\\s*import\\s+(\\w+)` gets all three wrong, and it gets them wrong SILENTLY: an
    unresolved receiver produces no finding, so every aliased import was simply never checked.
    A missed alias is not a smaller version of the bug -- it is the whole file going unexamined
    while the report says zero. Python's own parser already answers this exactly, so it is
    asked rather than approximated.

    Returns {local name: ("module", bound, ensure) or ("attr", module, attribute)}, where
    `ensure` is the module to import first so that submodule attributes are attached.
    """
    bindings = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return bindings
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = ("module", alias.name, alias.name)
                else:
                    # `import a.b` binds `a`, never `a.b`. The full path is still imported so
                    # that `a.b` resolves as an attribute of `a` afterwards.
                    root = alias.name.split(".")[0]
                    bindings[root] = ("module", root, alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                if alias.name == "*":
                    continue          # what a star import binds is not decidable from here
                bindings[alias.asname or alias.name] = ("attr", node.module, alias.name)
    return bindings


def binding_object(bindings, name):
    """The live object a local name is bound to, or None when it cannot be settled."""
    entry = bindings.get(name)
    if entry is None:
        return None
    try:
        if entry[0] == "module":
            importlib.import_module(entry[2])
            return importlib.import_module(entry[1])
        return getattr(importlib.import_module(entry[1]), entry[2])
    except Exception:                    # noqa: BLE001  not installed -> unknown, not absent
        return None


def local_binding(source: str, variable: str):
    """What class was this variable built from? `client = Client()` -> `Client`.

    WHY THIS EXISTS. Most third-party fabrication does not happen on a module:

        client = Client()
        rows = client.table("Name", "Age")        <- Client has no .table()

    A checker that only understands `module.name(` goes silent here, which is honest and
    useless -- local receivers are where the majority of invented methods actually live.

    ONLY THE UNAMBIGUOUS CASE IS RESOLVED. A variable bound exactly once, directly from calling
    an imported name. Every other binding -- a rebinding, a loop target, a parameter, a value
    built from an expression -- returns None, because guessing a type here produces false
    alarms on correct code, and that is the one failure this tool must not have.
    """
    escaped = re.escape(variable)
    # Every binding counts, not only the ones that look like constructor calls. Counting only
    # `x = Something(...)` means a later `x = 5` is invisible, and methods get resolved against
    # a class the variable no longer holds.
    bindings = re.findall(rf"^\s*{escaped}\s*(?:=[^=]|\+=|-=|\*=|/=)", source, re.M)
    others = re.findall(rf"^\s*(?:for\s+{escaped}\b|def\s+\w+\([^)]*\b{escaped}\b)", source, re.M)
    if len(bindings) + len(others) != 1:
        return None
    constructors = re.findall(rf"^\s*{escaped}\s*=\s*([A-Za-z_][\w.]*)\s*\(", source, re.M)
    return constructors[0] if len(constructors) == 1 else None


def _class_has(source: str, class_path: str, attribute: str):
    """Does the class a variable was built from actually have this method?"""
    root = class_path.split(".")[0]
    obj = binding_object(import_bindings(source), root)
    if obj is None:
        return None
    try:
        for part in class_path.split(".")[1:]:
            obj = getattr(obj, part)
        return hasattr(obj, attribute)
    except Exception:                    # noqa: BLE001
        return None


def resolve_exists(source: str, point, language: str = "python"):
    """True, False, or None for `receiver.name(` and `from module import name` sites."""
    if language != "python":
        return None                      # no interpreter to ask; honest unknown
    if point.get("kind") == "import":
        return module_has(point["module"], point["token"])

    lines = source.splitlines()
    if not 1 <= point["line"] <= len(lines):
        return None
    line = lines[point["line"] - 1]

    match = None
    for candidate in re.finditer(r"([A-Za-z_][\w.]*)\s*\.\s*([A-Za-z_]\w*)\s*\(", line):
        if candidate.group(2) == point["token"]:
            match = candidate
    if not match:
        return None                      # not a `receiver.name(` site

    owner = match.group(1)
    root = owner.split(".")[0]

    # WHAT THE RECEIVER NAME ACTUALLY BINDS TO. Getting this wrong is a false alarm on correct
    # code, which is the most damaging thing this tool can do -- and it did, before this was
    # fixed:
    #
    #     from datetime import datetime
    #     stamp = datetime.fromisoformat(text)     <- CORRECT
    #
    # An earlier version matched the import, resolved `datetime` as the MODULE, asked whether
    # the module has `fromisoformat`, and reported correct code as fabricated. It does not; the
    # CLASS does. `from X import Y` binds Y to X.Y, not to X, and that is what must be checked.
    bindings = import_bindings(source)
    if root in bindings:
        base = binding_object(bindings, root)
        if base is None:
            return None                  # named by an import that would not load -> unknown
    else:
        class_path = local_binding(source, root)
        return _class_has(source, class_path, point["token"]) if class_path else None

    try:
        obj = base
        for part in owner.split(".")[1:]:
            obj = getattr(obj, part)
        return hasattr(obj, point["token"])
    except Exception:                    # noqa: BLE001
        return None
