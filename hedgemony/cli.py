"""The command line. One argument is enough; everything else has a working default.

    hedgemony app.py                    check one file
    hedgemony src/                      check a directory
    hedgemony src/ --report             also write a report beside each file
    hedgemony app.py --report html      write the page instead of the markdown
    hedgemony src/ --json               machine-readable, for a pipeline
    hedgemony app.py --online           also ask registries about uninstalled packages
    hedgemony app.py --no-run           never run the checked file; names only

EXIT CODES, so this is usable in a pipeline without parsing text:

    0   nothing found
    1   at least one fabrication or broken contract
    2   the tool could not run

NOTHING TO CONFIGURE. There is no config file, no plugin path, and no project setup. A file and
a Python interpreter are the whole requirement, and every default is chosen so that the first
run on an unfamiliar codebase is the useful one.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .contracts import check_contracts
from .environment import RemoteScanner, describe, find_interpreter, is_same_environment
from .report import render_text, write_report
from .sandbox import Limits
from .scan import LANGUAGE_BY_SUFFIX, scan

SKIP_DIRECTORIES = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
                    "node_modules", ".tox", ".mypy_cache", ".pytest_cache", "build",
                    "dist", ".eggs", "site-packages", ".idea", ".vscode"}


def _is_sidecar(filename):
    """macOS AppleDouble sidecars, which are not source code even though they end in `.py`.

    On any filesystem that does not carry native metadata -- exFAT and FAT32 memory cards and
    external drives, most network shares, some archives -- macOS stores a file's metadata in a
    second hidden file named `._` plus the original name. So `app.py` acquires a companion
    `._app.py` holding a few kilobytes of binary.

    They match every source glob and they are not source, so they are skipped by name wherever
    files are gathered. Nothing else in the tool needs to know about them.
    """
    return os.path.basename(filename).startswith("._")


def collect(paths, recurse=True):
    """Every source file under the given paths, in a stable order.

    Report files this tool wrote are skipped, so pointing it at a directory twice never turns
    its own output into input. Hidden directories and dependency trees are skipped because
    checking a vendored copy of somebody else's library is noise, not signal.
    """
    found = []
    for path in paths:
        if os.path.isfile(path):
            if not _is_sidecar(path):
                found.append(path)
            continue
        if not os.path.isdir(path):
            print(f"hedgemony: no such file or directory: {path}", file=sys.stderr)
            continue
        for root, directories, files in os.walk(path):
            directories[:] = sorted(d for d in directories
                                    if d not in SKIP_DIRECTORIES and not d.startswith("."))
            for filename in sorted(files):
                if ".hedgemony." in filename or _is_sidecar(filename):
                    continue
                if os.path.splitext(filename)[1].lower() in LANGUAGE_BY_SUFFIX:
                    found.append(os.path.join(root, filename))
            if not recurse:
                break
    return found


def prepare_scans(args, files, announce=True):
    """Choose the interpreter that answers, and scan there when it is a different environment.

    WHICH INTERPRETER ANSWERS. Every verdict is decided by asking an interpreter whether a name
    exists, so asking the wrong one produces silence rather than answers. When the code belongs
    to another environment the scan is run there instead.

    Shared by the file listing and the board. It was not, once, and the board therefore always
    used hedgemony's own interpreter -- which meant a dependency-heavy project could be ranked
    clean because none of its libraries were visible to the thing scoring it. A ranking that
    silently measures the wrong environment is worse than no ranking, because it looks like a
    result.
    """
    interpreter = (sys.executable if args.python == "self"
                   else find_interpreter(args.python, near=args.paths[0]))
    if is_same_environment(interpreter):
        return interpreter, {}

    with RemoteScanner(interpreter, online=args.online) as scanner:
        works, why = scanner.usable()
        if works:
            if announce:
                print(f"  using the interpreter that owns this code: "
                      f"{describe(interpreter)}\n")
            return interpreter, scanner.scan_files(files)

    # Falling back rather than failing. A partial answer from this interpreter, with every
    # unresolvable package named, is worth more than no answer at all -- and the reason is
    # stated so nobody mistakes the reduced result for a full one.
    print(f"  {interpreter} cannot run the scan ({why}).\n"
          f"  Falling back to this interpreter; anything it does not have installed "
          f"will be listed as NOT CHECKED.\n", file=sys.stderr)
    return sys.executable, {}


def run_board(args, limits, use_colour):
    """Rank each given directory and write the ranking in whichever format was asked for."""
    from .board import rank                     # imported here: board imports collect from us
    from .report import render_board_html, render_board_markdown, render_board_text

    directories = [p for p in args.paths if os.path.isdir(p)]
    if not directories:
        print("hedgemony: --board needs directories to compare", file=sys.stderr)
        return 2

    try:
        interpreter, remote = prepare_scans(args, collect(directories),
                                            announce=not args.json)
    except FileNotFoundError as exc:
        print(f"hedgemony: {exc}", file=sys.stderr)
        return 2

    sources = rank(directories, run_contracts=not args.no_run, limits=limits,
                   interpreter=interpreter, scans=remote)

    if args.json:
        print(json.dumps({s.label: s.as_dict() for s in sources}, indent=2))
    else:
        print(render_board_text(sources, colour=use_colour))

    if args.out or args.report:
        # The extension decides the format when one is given, so `--out board.html` needs no
        # second flag to say what it means.
        target = args.out or os.path.join(os.path.dirname(os.path.abspath(directories[0])),
                                          f"hedgemony-board.{'html' if args.report == 'html'
                                                         else 'md'}")
        body = (render_board_html(sources) if target.endswith(".html")
                else render_board_markdown(sources))
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(body)
        if not args.json:
            print(f"  written: {target}\n")

    return 1 if any(s.fabrications or s.contracts_broken for s in sources) else 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hedgemony",
        description="Find the things an AI made up: packages, modules, attributes and calls "
                    "that do not exist, and code that contradicts its own stated examples.",
        epilog="A clean result means no fabricated name was found. It is not a proof that the "
               "code is correct.")
    parser.add_argument("paths", nargs="*", default=["."],
                        help="files or directories to check (default: the current directory)")
    parser.add_argument("--report", nargs="?", const="md", choices=["md", "html", "both"],
                        help="write a report beside each file: `md` to read anywhere, `html` "
                             "for a page, `both` for each. One fixed name per file, "
                             "overwritten each run")
    parser.add_argument("--board", action="store_true",
                        help="rank each given directory by fabrications per 100 lines, best "
                             "first, instead of listing files")
    parser.add_argument("--out", metavar="PATH",
                        help="where to write the ranking (default: beside the first path). "
                             "The extension chooses the format: .md or .html")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--online", action="store_true",
                        help="ask package registries about uninstalled imports (off by "
                             "default: the names looked up come from generated code)")
    parser.add_argument("--no-run", action="store_true",
                        help="never run the checked file; check names only. Its dependencies are still imported, which is what deciding a name costs")
    parser.add_argument("--python", metavar="PATH",
                        help="the interpreter that owns the code being checked. Defaults to a "
                             "virtual environment found beside it, then an activated one, "
                             "then the interpreter running this. Pass `self` to force the "
                             "latter")
    parser.add_argument("--timeout", type=int, default=15, metavar="SECONDS",
                        help="wall-clock limit for running one file's examples (default: 15)")
    parser.add_argument("--memory", type=int, default=512, metavar="MB",
                        help="memory limit for running one file's examples (default: 512)")
    parser.add_argument("--no-colour", "--no-color", action="store_true", dest="no_colour",
                        help="plain output with no escape codes")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="print only files that have findings")
    parser.add_argument("--version", action="version", version=f"hedgemony {__version__}")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.online:
        os.environ["HEDGEMONY_ONLINE"] = "1"

    limits = Limits(wall_seconds=args.timeout, memory_mb=args.memory)
    use_colour = sys.stdout.isatty() and not args.no_colour

    if args.board:
        return run_board(args, limits, use_colour)

    files = collect(args.paths)
    if not files:
        print("hedgemony: nothing to check", file=sys.stderr)
        return 2

    try:
        interpreter, remote = prepare_scans(args, files, announce=not args.json)
    except FileNotFoundError as exc:
        print(f"hedgemony: {exc}", file=sys.stderr)
        return 2

    payload = {}
    total_findings = total_lines = 0
    broken_contracts = 0

    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError as exc:
            print(f"hedgemony: cannot read {path}: {exc}", file=sys.stderr)
            continue

        result = remote.get(path) or scan(path)
        if "error" in result:
            print(f"hedgemony: {path}: {result['error']}", file=sys.stderr)
            continue
        contract = None
        if not args.no_run and result["language"] == "python":
            contract = check_contracts(path, limits=limits, interpreter=interpreter)
            if contract.status == "VIOLATED":
                broken_contracts += len(contract.findings)

        total_findings += len(result["findings"])
        total_lines += result["lines"]

        if args.json:
            payload[path] = {
                "language": result["language"],
                "lines": result["lines"],
                "rate": round(result["rate"], 2),
                "findings": result["findings"],
                "unchecked_imports": result.get("unchecked_imports", []),
                "contracts": {
                    "status": contract.status if contract else "SKIPPED",
                    "examples": contract.examples if contract else 0,
                    "findings": contract.findings if contract else [],
                    "error": contract.error if contract else None,
                },
            }
        else:
            interesting = result["findings"] or (contract and contract.status == "VIOLATED")
            if interesting or not args.quiet:
                print(render_text(path, result, contract, colour=use_colour))
                print()

        if args.report:
            formats = ["md", "html"] if args.report == "both" else [args.report]
            for fmt in formats:
                written = write_report(path, source, result, contract, fmt=fmt)
                if not args.json and not args.quiet:
                    print(f"    report: {written}")
            if not args.json and not args.quiet:
                print()

    if args.json:
        print(json.dumps(payload, indent=2))
    elif len(files) > 1:
        rate = 100.0 * total_findings / max(1, total_lines)
        print(f"  TOTAL {total_findings} fabrication(s) in {total_lines} lines across "
              f"{len(files)} file(s) = {rate:.1f} per 100 lines")
        if broken_contracts:
            print(f"  {broken_contracts} stated example(s) did not hold")

    return 1 if (total_findings or broken_contracts) else 0


if __name__ == "__main__":
    sys.exit(main())
