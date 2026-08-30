"""Bounded execution for code nobody has read.

WHY THIS EXISTS. Checking whether code does what it claims requires running it, and the code
being checked was written by a machine. Running it in this process would mean an infinite loop
hangs the tool, a runaway allocation takes the machine down with it, and anything the code
writes lands wherever the tool happens to be pointed. So nothing is ever executed here. Every
run happens in a separate interpreter, in its own process group, under resource limits applied
before any of the target's code runs, in a directory created for that run and destroyed after
it. The result comes back on a private channel rather than on the target's own output stream,
so nothing the target prints can be read as a verdict.

WHAT THIS IS AND IS NOT, stated plainly because the distinction matters:

    IT IS      a blast-radius limiter. Accidents stay small and stay contained.
    IT IS NOT  a security boundary against code that is deliberately trying to escape.

Real isolation against a determined attacker needs a container or a VM, which needs privileges
this tool does not ask for. If the code under test may be hostile rather than merely wrong, run
the whole tool inside a container. That is documented rather than papered over, because a tool
that overstates its own containment is more dangerous than one that has none.

WHAT IS ENFORCED, and by what:

    CPU seconds        kernel (RLIMIT_CPU)      an infinite loop dies on its own
    wall seconds       parent, SIGKILL to the   a process ignoring signals still dies
                       whole process group
    memory             the parent polling the   see below -- no kernel limit is portable
                       group, and the child
                       watching itself
    file size          kernel (RLIMIT_FSIZE)    cannot fill a disk
    process count      kernel (RLIMIT_NPROC)    cannot fork without bound
    open files         kernel (RLIMIT_NOFILE)
    network            refused in the child     sockets raise before any connection
    environment        stripped to five vars    tokens and keys are not visible
    working directory  fresh, removed after     writes land in a directory that is deleted

WHY MEMORY IS NOT LEFT TO THE KERNEL. There are limits for this and on some platforms they
work. On macOS all three were measured taking a 200 MB allocation under a 64 MB cap without
complaint:

    RLIMIT_AS      not enforced
    RLIMIT_DATA    not enforced
    RLIMIT_RSS     not enforced

A guard whose behaviour depends on which machine it runs on is not a guard, so the ceiling is
enforced in software, from two directions at once:

    the parent   samples the whole process group and kills it when the total goes over.
                 Each look costs a process, so it cannot be done very often -- but it is the
                 only one that sees memory held by children, or that works at all when the
                 child has stopped responding.

    the child    checks its own peak usage on a short interval and exits if it is over. From
                 inside, the question is one library call, so it can be asked far more often
                 and closes most of the gap between the parent's looks.

Neither replaces the other. Together, a 200 MB block allocated and dropped six times in a row
under a 64 MB limit is stopped in under a third of a second -- a shape that defeats sampling on
its own. The kernel limits are still requested, because where they ARE enforced they fail the
allocation faster and more cleanly than any check can; they are simply never depended upon.

It is still a small window rather than a hard ceiling. Code that must not be able to spike at
all belongs in a container with a real memory cgroup, and this says so rather than pretending
otherwise.

Each limit is applied independently and a platform refusing one never prevents the others from
being applied.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

__all__ = ["Limits", "DEFAULT_LIMITS", "run_isolated", "Result"]

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_runner.py")

# Kept in step with `_runner.MEMORY_EXIT`. Declared here rather than imported because the runner
# is a script executed in another interpreter, never a module of this one.
MEMORY_EXIT = 93


class Limits:
    """Every bound applied to an isolated run. Defaults are deliberately small.

    A contract example that needs more than a second of CPU or half a gigabyte of memory is
    not a contract example, so the defaults are set where honest work fits and runaway work
    does not. They are raised explicitly by the caller or not at all.
    """

    __slots__ = ("cpu_seconds", "wall_seconds", "memory_mb", "file_mb",
                 "processes", "open_files", "output_bytes", "allow_network")

    def __init__(self, cpu_seconds=5, wall_seconds=15, memory_mb=512, file_mb=8,
                 processes=64, open_files=256, output_bytes=256 * 1024, allow_network=False):
        self.cpu_seconds = cpu_seconds
        self.wall_seconds = wall_seconds
        self.memory_mb = memory_mb
        self.file_mb = file_mb
        self.processes = processes
        self.open_files = open_files
        self.output_bytes = output_bytes
        self.allow_network = allow_network

    def as_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


DEFAULT_LIMITS = Limits()


class Result:
    """What came back from an isolated run.

    `ok` means the run completed and the child reported success. It is deliberately separate
    from `timed_out` and `killed`, because a run that was terminated has NOT proven anything --
    reporting a timeout as a failed contract would blame the code for the tool's own limit.
    """

    __slots__ = ("ok", "timed_out", "killed", "over_memory", "peak_memory_mb",
                 "exit_code", "stdout", "stderr", "payload")

    def __init__(self, ok, timed_out, killed, exit_code, stdout, stderr, payload,
                 over_memory=False, peak_memory_mb=0.0):
        self.ok = ok
        self.timed_out = timed_out
        self.killed = killed
        self.over_memory = over_memory
        self.peak_memory_mb = peak_memory_mb
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.payload = payload

    @property
    def stopped(self):
        """Was the run cut short by a limit? Then it has proven nothing about the code."""
        return self.timed_out or self.killed or self.over_memory

    def __repr__(self):
        return (f"Result(ok={self.ok}, timed_out={self.timed_out}, killed={self.killed}, "
                f"over_memory={self.over_memory}, peak_mb={self.peak_memory_mb:.0f}, "
                f"exit_code={self.exit_code})")


def _limits_for_child(lim: Limits):
    """The resource limits, in the form the child applies to itself.

    They are applied by the child rather than by a between-fork-and-exec hook, because that
    hook is documented as unsafe in a program with threads and this one has them -- output is
    drained on threads so that a target filling a pipe cannot deadlock the run. See
    `_runner._apply_limits`.
    """
    return json.dumps({
        "cpu": lim.cpu_seconds,
        "fsize": lim.file_mb * 1024 * 1024,
        "nproc": lim.processes,
        "nofile": lim.open_files,
        "mem": lim.memory_mb * 1024 * 1024,
    })


def _clean_env(workdir: str, lim: Limits):
    """The child sees four variables and nothing else.

    Executed code inherits the environment of whatever launched it, and a developer's
    environment routinely holds API keys, session tokens and cloud credentials. None of that
    is needed to run a contract example, so none of it is passed. PATH is kept minimal because
    a child with no PATH breaks in confusing ways rather than safe ones.
    """
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": workdir,
        "TMPDIR": workdir,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "HEDGEMONY_ALLOW_NETWORK": "1" if lim.allow_network else "0",
        # The child enforces the same ceiling from the inside, where it can check far more
        # often than the parent can afford to.
        "HEDGEMONY_MEMORY_MB": str(lim.memory_mb),
    }


def _kill_group(proc):
    """Terminate the child AND anything it started.

    Killing the process alone is not enough: a child that spawned its own children leaves them
    running, holding CPU and memory after the tool believes the run is over. The child is put
    in a new session at launch precisely so the whole group can be signalled by one call.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:
            pass


def _group_memory_mb(pgid: int) -> float:
    """Resident memory of every process in the group, in megabytes.

    The whole group is summed rather than just the first process, because a target that spawns
    children can hold far more memory than its own resident size shows. `ps` reports resident
    size in kilobytes on every platform this runs on. If it cannot be read at all -- it is
    missing, slow, or refused -- the answer is 0.0, which lets the wall clock remain the bound
    rather than killing a healthy run on a failed measurement.
    """
    try:
        out = subprocess.run(["/bin/ps", "-Ao", "pgid=,rss="],
                             capture_output=True, text=True, timeout=5)
    except Exception:
        return 0.0
    total = 0
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].lstrip("-").isdigit() and parts[1].isdigit():
            if int(parts[0]) == pgid:
                total += int(parts[1])
    return total / 1024.0


def _drain_fd(fd, sink):
    """Read the result channel to end-of-file, on a thread so a full pipe cannot wedge it."""
    try:
        while True:
            chunk = os.read(fd, 8192)
            if not chunk:
                break
            sink.append(chunk)
    except OSError:
        pass


def _drain(stream, sink):
    try:
        for chunk in iter(lambda: stream.read(8192), ""):
            if not chunk:
                break
            sink.append(chunk)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _supervise(proc, lim: Limits):
    """Watch the run until it ends or breaches a bound. Returns (out, err, flags).

    Output is drained on threads throughout. Reading only at the end would deadlock the moment
    a target writes more than a pipe buffer holds, which a runaway loop printing in a loop does
    within milliseconds -- the process would block on a full pipe, never exit, and the timeout
    would be blamed on the code rather than on the tool.
    """

    out_parts, err_parts = [], []
    threads = [threading.Thread(target=_drain, args=(proc.stdout, out_parts), daemon=True),
               threading.Thread(target=_drain, args=(proc.stderr, err_parts), daemon=True)]
    for t in threads:
        t.start()

    try:
        pgid = os.getpgid(proc.pid)
    except Exception:
        pgid = proc.pid

    started = time.monotonic()
    peak = 0.0
    timed_out = over_memory = False
    poll_interval = 0.1
    next_memory_check = 0.0

    while proc.poll() is None:
        elapsed = time.monotonic() - started
        if elapsed >= lim.wall_seconds:
            timed_out = True
            _kill_group(proc)
            break
        if elapsed >= next_memory_check:
            used = _group_memory_mb(pgid)
            peak = max(peak, used)
            if used > lim.memory_mb:
                over_memory = True
                _kill_group(proc)
                break
            next_memory_check = elapsed + poll_interval
        time.sleep(0.02)

    try:
        proc.wait(timeout=5)
    except Exception:
        _kill_group(proc)
    for t in threads:
        t.join(timeout=5)

    return ("".join(out_parts), "".join(err_parts),
            {"timed_out": timed_out, "over_memory": over_memory, "peak_memory_mb": peak})


def run_isolated(target: str, mode: str = "contracts", limits: Limits = None,
                 interpreter: str = None) -> Result:
    """Run `target` in a bounded child interpreter and return what it reported.

    Nothing from the target is imported, evaluated or inspected in this process. The only
    thing that crosses back is text on a pipe, parsed as JSON.

    `interpreter` selects which Python runs the file. It defaults to the one running this, and
    is set to the target project's interpreter when the code under test belongs to a different
    environment -- an example that imports the project's own dependencies can only run where
    those dependencies exist.
    """
    lim = limits or DEFAULT_LIMITS
    python = interpreter or sys.executable
    target = os.path.abspath(target)
    workdir = tempfile.mkdtemp(prefix="hedgemony-run-")

    # THE RESULT TRAVELS ON ITS OWN CHANNEL, not on stdout. The target prints to stdout, so a
    # result sharing that stream could be imitated by anything the target chose to print. This
    # pipe is separate: whatever the target writes to stdout or stderr cannot reach it.
    #
    # WHAT THIS DOES NOT DO, stated exactly. The child is told the descriptor number, so code
    # that deliberately reads HEDGEMONY_RESULT_FD can write a result of its own choosing and
    # close it. The guarantee here is that the target's OUTPUT cannot be mistaken for a result
    # -- an accident, and the realistic case. It is not unforgeability against code written to
    # attack this protocol; that would need a different process boundary, and the tool's stated
    # scope is bounding accidents rather than containing hostile code. Anything genuinely
    # untrusted belongs behind `--no-run`, which never starts a child at all.
    read_fd, write_fd = os.pipe()
    environment = _clean_env(workdir, lim)
    environment["HEDGEMONY_RESULT_FD"] = str(write_fd)
    environment["HEDGEMONY_LIMITS"] = _limits_for_child(lim)

    try:
        # `-I` is isolated mode: the user site directory is ignored, PYTHON* variables are
        # ignored, and the current directory is kept off sys.path. It closes the simplest way
        # for executed code to pick up something it was not given.
        argv = [python, "-I", "-B", RUNNER, target, mode]
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=workdir,
            env=environment,
            pass_fds=(write_fd,),
            start_new_session=True,       # own process group, so the whole tree is killable
            text=True,
        )
        # Closed in the parent immediately, so the read end reaches end-of-file as soon as the
        # child exits. Holding it open here would make the read block until the timeout.
        os.close(write_fd)
        write_fd = None

        result_parts = []
        reader = threading.Thread(target=_drain_fd, args=(read_fd, result_parts), daemon=True)
        reader.start()

        out, err, flags = _supervise(proc, lim)
        reader.join(timeout=5)
        out = (out or "")[: lim.output_bytes]
        err = (err or "")[: lim.output_bytes]
        timed_out = flags["timed_out"]

        payload = None
        raw = b"".join(result_parts)[: lim.output_bytes]
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                payload = None
        code = proc.returncode
        # A negative return code is a signal: the kernel stopped it (CPU limit, memory, our
        # own kill). That is not a verdict about the code and is never reported as one.
        killed = code is not None and code < 0
        # The child stops itself on this code when it notices it is over the ceiling before the
        # parent's next sample. Either route means the same thing: the run was cut short by
        # memory and has proven nothing about the code.
        over = flags["over_memory"] or code == MEMORY_EXIT
        return Result(ok=(payload is not None and not timed_out and not killed and not over),
                      timed_out=timed_out, killed=killed, exit_code=code,
                      stdout=out, stderr=err, payload=payload,
                      over_memory=over, peak_memory_mb=flags["peak_memory_mb"])
    finally:
        for fd in (read_fd, write_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        shutil.rmtree(workdir, ignore_errors=True)
