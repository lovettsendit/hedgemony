"""Does the sandbox actually contain anything? -- checked against hostile input.

A containment claim is worthless until something has tried to escape it, so every guard here
is tested by code written to defeat that specific guard.

THE RULE EVERY PAYLOAD FOLLOWS: it must be harmless if the guard fails. A memory test that
would exhaust the machine when the memory limit does not work is not a test, it is the
accident it claims to prevent. So the allocation probe asks for an amount that is fatal to a
64 MB limit and unremarkable to a machine, the fork probe is bounded to a count no system
notices, and the wall-clock kill backs all of them. This matters because one limit here is
genuinely not enforced on every platform, and the test has to survive discovering that.
"""
from __future__ import annotations

import os
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from hedgemony.sandbox import Limits, run_isolated       # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    mark = "ok  " if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))


def payload(body: str, tmp="probe.py"):
    """Write a probe file and return its path. Never executed in this process."""
    import tempfile
    d = tempfile.mkdtemp(prefix="hedgemony-probe-")
    p = os.path.join(d, tmp)
    with open(p, "w") as fh:
        fh.write(textwrap.dedent(body))
    return p


def main():
    print("\nSANDBOX CONTAINMENT -- each guard tested with code written to defeat it\n")

    # ---------------------------------------------------------------- baseline: it works at all
    p = payload('''
        def double(x):
            """Twice x.

            >>> double(4)
            8
            """
            return x * 2
        ''')
    r = run_isolated(p)
    check("a correct file runs and reports no failures",
          r.ok and r.payload and not r.payload["failures"],
          f"examples={r.payload['examples'] if r.payload else '?'}")

    # ---------------------------------------------------------------- a real broken contract
    p = payload('''
        import math

        def pages_needed(items, per_page):
            """How many pages are needed to show every item.

            >>> pages_needed(10, 3)
            4
            """
            return math.floor(items / per_page)
        ''')
    r = run_isolated(p)
    check("a violated contract is caught",
          r.ok and r.payload and len(r.payload["failures"]) == 1,
          r.payload["failures"][0]["statement"] if r.ok and r.payload["failures"] else "")

    # ---------------------------------------------------------------- CPU: an infinite loop
    # Left alone this never returns. The CPU limit has to end it without the parent doing
    # anything, so the wall clock is set well above the CPU limit -- if the wall clock were
    # what stopped it, this would be testing the wrong guard.
    p = payload("while True:\n    pass\n")
    r = run_isolated(p, limits=Limits(cpu_seconds=2, wall_seconds=30))
    check("an infinite loop is stopped by the CPU limit, not by the wall clock",
          (r.killed or r.exit_code not in (0,)) and not r.timed_out,
          f"exit={r.exit_code} timed_out={r.timed_out}")

    # ---------------------------------------------------------------- memory
    # 200 MB held: fatal to a 64 MB limit, unremarkable to any machine even if every guard
    # fails. The buffer is HELD rather than allocated and dropped, because held memory is what
    # a runaway actually does and what sampling is designed to catch.
    p = payload('''
        import time
        buf = bytearray(200 * 1024 * 1024)
        time.sleep(4)
        print("SURVIVED", len(buf))
        ''')
    r = run_isolated(p, limits=Limits(memory_mb=64, wall_seconds=20))
    check("held memory over the limit is stopped, on any platform",
          r.over_memory and "SURVIVED" not in (r.stdout or ""),
          f"peak {r.peak_memory_mb:.0f} MB against a 64 MB limit")

    # ---------------------------------------------------------------- memory: a fast spike
    # The parent samples the process group on an interval, so memory taken and released
    # between two samples can pass unseen. The child therefore also watches itself, where the
    # same question costs a library call instead of a process and can be asked far more often.
    # This probe allocates and drops repeatedly, which is the shape that defeats sampling
    # alone. Each allocation is still small enough to be harmless if every guard fails.
    p = payload('''
        for _ in range(6):
            block = bytearray(200 * 1024 * 1024)
            del block
        print("SURVIVED")
        ''')
    r = run_isolated(p, limits=Limits(memory_mb=64, wall_seconds=30))
    check("memory taken and released between samples is still caught",
          r.over_memory and "SURVIVED" not in (r.stdout or ""),
          "the child watches itself as well as being watched")

    # ---------------------------------------------------------------- processes
    # Bounded to 40 deliberately. An unbounded fork bomb would be the accident this suite
    # exists to prevent; 40 short-lived children prove the limit fires and cost nothing if it
    # does not.
    p = payload('''
        import os
        made = 0
        for _ in range(40):
            try:
                pid = os.fork()
            except OSError:
                break
            if pid == 0:
                os._exit(0)
            made += 1
        print("forked", made)
        ''')
    r = run_isolated(p, limits=Limits(processes=8, wall_seconds=20))
    forked = 999
    for line in (r.stdout or "").splitlines():
        if line.startswith("forked"):
            forked = int(line.split()[1])
    check("forking is capped", forked < 40, f"managed {forked} of 40 attempts")

    # ---------------------------------------------------------------- network
    # The address is TEST-NET-1 (RFC 5737), reserved for documentation and guaranteed not to
    # route anywhere. If the guard were ever to fail, this test still contacts nothing real --
    # a containment test must not itself reach the internet to prove containment.
    p = payload('''
        import socket
        s = socket.socket()
        s.settimeout(2)
        s.connect(("192.0.2.1", 80))
        print("CONNECTED")
        ''')
    r = run_isolated(p)
    check("outbound network is refused", "CONNECTED" not in (r.stdout or ""),
          "socket layer blocked before the target loads")

    # ---------------------------------------------------------------- file size
    p = payload('''
        with open("big.bin", "wb") as fh:
            for _ in range(200):
                fh.write(b"x" * (1024 * 1024))
        print("WROTE 200MB")
        ''')
    r = run_isolated(p, limits=Limits(file_mb=4, wall_seconds=20))
    check("writes are capped by file size limit", "WROTE 200MB" not in (r.stdout or ""),
          "cap held at 4 MB")

    # ---------------------------------------------------------------- credentials
    # The strongest reason to strip the environment: a developer's shell holds tokens, and
    # executed code inherits whatever it is given.
    os.environ["HEDGEMONY_TEST_FAKE_TOKEN"] = "must-not-be-visible"
    p = payload('''
        import os
        print("SAW", os.environ.get("HEDGEMONY_TEST_FAKE_TOKEN"))
        ''')
    r = run_isolated(p)
    leaked = "SAW must-not-be-visible" in (r.stdout or "")
    os.environ.pop("HEDGEMONY_TEST_FAKE_TOKEN", None)
    check("environment secrets are not visible to executed code", not leaked,
          "child sees a stripped environment")

    # ---------------------------------------------------------------- working directory
    p = payload('''
        import os
        open("side-effect.txt", "w").write("x")
        print("CWD", os.getcwd())
        ''')
    r = run_isolated(p)
    cwd = next((l.split(" ", 1)[1] for l in (r.stdout or "").splitlines()
                if l.startswith("CWD")), "")
    check("writes land in a temporary directory that is removed",
          bool(cwd) and not os.path.exists(os.path.join(cwd, "side-effect.txt")),
          "run directory deleted after the run")

    # ---------------------------------------------------------------- a timeout is not a verdict
    p = payload('''
        import time
        time.sleep(60)
        ''')
    r = run_isolated(p, limits=Limits(cpu_seconds=30, wall_seconds=3))
    check("a run that times out is reported as a timeout, never as a failed contract",
          r.timed_out and not r.ok, "ok=False, timed_out=True")

    # ---------------------------------------------------------------- an import that raises
    p = payload('''
        raise RuntimeError("boom at import time")
        ''')
    r = run_isolated(p)
    check("a file that raises on import is reported, not swallowed",
          r.payload is not None and "error" in (r.payload or {}),
          (r.payload or {}).get("error", "")[:48])

    print("\nTHE TARGET'S OUTPUT CANNOT BE MISTAKEN FOR A RESULT\n")

    # SCOPE, because the difference matters. The result used to share stdout with the target,
    # so a file that merely PRINTED something shaped like a result was read as one -- an
    # accident, and the realistic case. That is what is closed here and what is tested below.
    #
    # This is NOT unforgeability against an attacker. The child is told the descriptor number,
    # so code written to target this protocol can open it and write whatever it likes. That is
    # consistent with the documented scope -- the sandbox bounds accidents, it is not a
    # security boundary -- and the honest claim is the narrow one. Untrusted code belongs
    # behind `--no-run`, which starts no child at all.
    #
    # This probe prints a fabricated verdict claiming everything held, and it must have no
    # effect at all.
    p = payload('''
        import json
        print("__HEDGEMONY__" + json.dumps(
            {"kind": "contracts", "examples": 99, "failures": []}))

        def broken():
            """
            >>> broken()
            1
            """
            return 2
        ''')
    r = run_isolated(p)
    forged = bool(r.payload and r.payload.get("examples") == 99)
    check("a target printing a fake result on stdout is ignored", not forged,
          "the result channel is separate from the target's output")
    check("and the real failure is still reported",
          r.ok and r.payload and len(r.payload["failures"]) == 1,
          "the genuine verdict survives the attempt")

    # The high-level `socket` names are replaced, but `socket` is a thin wrapper over the
    # built-in `_socket`; leaving that reachable would let anything bypass the block by
    # importing it directly.
    p = payload('''
        import _socket
        try:
            s = _socket.socket()
            print("REACHED THE SOCKET LAYER")
        except Exception as exc:
            print("refused:", type(exc).__name__)
        ''')
    r = run_isolated(p)
    check("the network block is not bypassed by importing the low-level socket module",
          "REACHED THE SOCKET LAYER" not in (r.stdout or ""),
          (r.stdout or "").strip().splitlines()[-1][:50] if r.stdout else "")

    # Limits are applied by the child now rather than between fork and exec, because that hook
    # is unsafe in a threaded program. They must still hold.
    p = payload('''
        import resource
        soft, _hard = resource.getrlimit(resource.RLIMIT_NPROC)
        print("NPROC", soft)
        ''')
    r = run_isolated(p, limits=Limits(processes=11))
    reported = next((l.split()[1] for l in (r.stdout or "").splitlines()
                     if l.startswith("NPROC")), "")
    check("limits are in force before the target's own code runs",
          reported == "11", f"the target sees NPROC={reported or '?'}")

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
