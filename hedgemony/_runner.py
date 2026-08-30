"""The child process. Runs inside the sandbox and never imported by the tool.

This file is executed as a script in a separate interpreter under kernel limits. It is the
only place where code under test is ever imported, and it exists as its own file so that
nothing here can be reached by accident from the parent.

The guards below are installed BEFORE the target is loaded, because importing a module runs
its top-level statements. By the time a target's own code is reachable, every guard is already
in place.

One line of output matters: a single `__HEDGEMONY__` line carrying JSON. Everything the target
prints is left alone on the surrounding lines, so a target that writes to stdout cannot
corrupt the result by printing something that looks like a report.
"""
from __future__ import annotations

import json
import sys


# Exit code the child uses when it stops itself for exceeding the memory ceiling. Distinct so
# the parent can tell "this run was cut short by memory" from any status the target produced.
MEMORY_EXIT = 93


class NetworkBlocked(OSError):
    """Raised in place of any outbound connection."""


def _watch_memory(limit_mb):
    """Stop this process if it goes over the ceiling, without waiting to be asked.

    WHY THE CHILD WATCHES ITSELF AS WELL AS THE PARENT. No kernel memory limit is enforced on
    every platform -- on macOS RLIMIT_AS, RLIMIT_DATA and RLIMIT_RSS were all measured taking a
    200 MB allocation under a 64 MB cap without complaint -- so the ceiling has to be enforced
    in software. The parent samples the whole process group, which is what catches a run that
    spawns children or stops responding, but sampling from outside costs a process per look and
    so cannot be done very often. From inside, the same question is a single library call, so
    it can be asked far more frequently and closes most of the gap between the parent's looks.

    Neither guard replaces the other: this one cannot see memory held by child processes, and
    the parent's cannot look often. Together the window in which a runaway goes unnoticed is
    small, and it is still a window rather than a hard ceiling -- a real one needs a container.
    """
    if not limit_mb or limit_mb <= 0:
        return
    import os
    import resource
    import threading
    import time

    # `ru_maxrss` is bytes on macOS and kilobytes on Linux. Getting this backwards would make
    # the guard either fire instantly or never, so it is chosen from the platform rather than
    # assumed.
    to_mb = (1.0 / (1024 * 1024)) if sys.platform == "darwin" else (1.0 / 1024)

    def loop():
        while True:
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * to_mb
            if peak > limit_mb:
                sys.stderr.write(f"hedgemony: stopped at {peak:.0f} MB, over the "
                                 f"{limit_mb:.0f} MB limit\n")
                sys.stderr.flush()
                os._exit(MEMORY_EXIT)
            time.sleep(0.02)

    threading.Thread(target=loop, daemon=True).start()


def _block_network():
    """Refuse sockets before the target is loaded.

    A contract example has no business opening a connection, and code that reaches for the
    network during a check is either wrong or doing something the person running this tool did
    not ask for. Refusing at the socket layer covers everything built on top of it, so no
    separate rule is needed per library.

    This is a guard against accident, not against a determined escape: code that is trying to
    get out can reach the syscall by other means. Containment for hostile input is the
    container, documented as such.
    """
    import socket

    def deny(*_a, **_k):
        raise NetworkBlocked("network access is disabled during checking")

    for name in ("socket", "create_connection", "create_server", "socketpair",
                 "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
        if hasattr(socket, name):
            setattr(socket, name, deny)

    # `socket` is a thin wrapper over the built-in `_socket`, so leaving that reachable would
    # let anything import it directly and open a connection with the wrapper untouched.
    try:
        import _socket
        for name in ("socket", "getaddrinfo", "gethostbyname"):
            if hasattr(_socket, name):
                setattr(_socket, name, deny)
    except ImportError:
        pass

    # The higher-level clients are built on the above and are already covered, but they cache
    # references at import time, so any imported before now would keep working. Blocking them
    # by name closes that.
    for module_name, attributes in (("urllib.request", ("urlopen",)),
                                    ("http.client", ("HTTPConnection", "HTTPSConnection"))):
        module = sys.modules.get(module_name)
        if module is not None:
            for name in attributes:
                if hasattr(module, name):
                    setattr(module, name, deny)


def _apply_limits():
    """Set this process's resource limits, before the target is loaded.

    WHY THESE ARE SET HERE RATHER THAN BY THE PARENT AT FORK TIME. `subprocess` offers a hook
    that runs between fork and exec, and it is the obvious place for this -- but that hook runs
    in a just-forked process and is documented as unsafe in any program with threads. This one
    has threads: output is drained on them, because a target that fills a pipe would otherwise
    deadlock. Rather than rely on the two never overlapping, the limits are applied here, in
    ordinary code, before anything of the target's has run. Same effect, no fork-safety
    question, and it works on platforms with no such hook at all.

    Each limit is applied on its own. A platform that refuses one -- macOS refuses every memory
    limit -- must never prevent the rest from being applied.
    """
    import os
    import resource

    try:
        wanted = json.loads(os.environ.get("HEDGEMONY_LIMITS") or "{}")
    except ValueError:
        return
    for name, value in (
        ("RLIMIT_CPU", (wanted.get("cpu"), wanted.get("cpu", 0) + 1)),
        ("RLIMIT_FSIZE", (wanted.get("fsize"),) * 2),
        ("RLIMIT_NPROC", (wanted.get("nproc"),) * 2),
        ("RLIMIT_NOFILE", (wanted.get("nofile"),) * 2),
        ("RLIMIT_AS", (wanted.get("mem"),) * 2),
    ):
        limit = getattr(resource, name, None)
        if limit is None or value[0] is None:
            continue
        try:
            resource.setrlimit(limit, (int(value[0]), int(value[1])))
        except (ValueError, OSError):
            pass
    os.umask(0o077)


def _emit(payload):
    """Send the result on its own channel, never on stdout.

    WHY NOT STDOUT. The target prints to stdout, and anything it prints sits in the same stream
    the result would. A file that happens to print a line looking like a result -- by accident
    or on purpose -- could otherwise be read as one. The parent opens a separate pipe and
    passes its number in; nothing the target writes to stdout or stderr can reach it, so the
    two can never be confused.
    """
    import os
    body = json.dumps(payload).encode()
    fd = os.environ.get("HEDGEMONY_RESULT_FD")
    if fd is not None:
        try:
            os.write(int(fd), body)
            os.close(int(fd))
            return
        except (OSError, ValueError):
            pass                          # channel unusable; fall through rather than lose it
    sys.stdout.write("\n__HEDGEMONY__" + body.decode() + "\n")
    sys.stdout.flush()


def _load(path):
    """Import the target file as a module under a name that cannot collide."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_hedgemony_target", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_hedgemony_target"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_contracts(path):
    """Execute every stated example in the file and report each one that did not hold.

    The report is per example rather than per file. A function with four examples where one
    fails is a different fact from a function that fails everywhere, and collapsing them would
    throw away the part that tells you where to look.
    """
    import doctest

    mod = _load(path)
    finder = doctest.DocTestFinder(exclude_empty=True)
    runner = doctest.DocTestRunner(verbose=False, optionflags=doctest.ELLIPSIS)

    failures = []
    examples = 0

    class Collect(doctest.OutputChecker):
        pass

    for test in finder.find(mod):
        if not test.examples:
            continue
        examples += len(test.examples)
        # ONE NAMESPACE FOR THE WHOLE DOCSTRING, not one per example. Examples build on each
        # other -- `>>> value = 2` and then `>>> value + 1` -- which is how doctest has always
        # worked and how people ordinarily write them. Giving each example its own copy of the
        # globals turned that into a NameError and reported correct code as a broken contract:
        # a false alarm, on the most common shape there is. Each example is still RUN
        # separately, because that is what locates a failure to one line; only the namespace is
        # shared. `DocTest.__init__` copies whatever it is handed, so what each example bound
        # is carried forward explicitly afterwards.
        globs = test.globs.copy()
        for example in test.examples:
            single = doctest.DocTest([example], globs, test.name,
                                     test.filename, test.lineno, test.docstring)
            out = []
            runner.run(single, out=out.append, clear_globs=False)
            globs.update(single.globs)
            if runner.failures:
                runner.failures = 0
                # `example.lineno` is relative to the docstring; `test.lineno` locates the
                # docstring in the file. Reporting an absolute line is what makes the finding
                # usable without the reader counting lines by hand.
                base = (test.lineno or 0) + 1
                failures.append({
                    "name": test.name,
                    "line": base + example.lineno,
                    "statement": example.source.strip(),
                    "expected": example.want.strip(),
                    "detail": "".join(out).strip()[-800:],
                })
    return {"kind": "contracts", "examples": examples, "failures": failures}


def main():
    if len(sys.argv) < 3:
        _emit({"error": "usage: _runner.py <target> <mode>"})
        return 2
    path, mode = sys.argv[1], sys.argv[2]

    import os
    _apply_limits()
    if os.environ.get("HEDGEMONY_ALLOW_NETWORK") != "1":
        _block_network()

    # Started before the target is loaded, because importing a module runs its top-level code
    # and that is as capable of running away as anything in a function.
    try:
        _watch_memory(float(os.environ.get("HEDGEMONY_MEMORY_MB") or 0))
    except (TypeError, ValueError):
        pass

    try:
        if mode == "contracts":
            _emit(_run_contracts(path))
        else:
            _emit({"error": f"unknown mode {mode!r}"})
            return 2
    except BaseException as exc:                      # noqa: BLE001
        # An import that raises is a fact about the file worth reporting, not a crash to hide.
        # It is reported as an error rather than as a failed contract, because the file never
        # got far enough for its contracts to be tested at all.
        _emit({"kind": "contracts", "error": f"{type(exc).__name__}: {exc}"[:400],
               "examples": 0, "failures": []})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
