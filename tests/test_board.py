"""Does the ranking put the right source first, and say why?

A leaderboard that orders things wrongly is worse than no leaderboard, because an ordering
reads as a judgement whether or not it earned one. The suite therefore builds sources whose
correct order is known in advance and checks the tool agrees -- including the case that got the
first version of this wrong.

THE ORDERING BUG THIS SUITE EXISTS TO PREVENT. Ranking on invented names alone put a source
with two failing examples ABOVE a source whose four examples all held, because neither had
invented a name. The worse code appeared to win. The rank is over every defect found, and the
case is pinned below so it cannot come back.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLES = os.path.join(ROOT, "examples")
sys.path.insert(0, ROOT)

from hedgemony.board import rank                             # noqa: E402
from hedgemony.report import render_board_html, render_board_markdown  # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  [{'ok  ' if condition else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def build():
    """Three sources whose correct order is known before anything runs.

        clean_source    no invented names, four stated examples, all holding   -> best
        logic_source    no invented names, two stated examples that FAIL       -> middle
        naming_source   two invented names, nothing stated                     -> worst
    """
    root = tempfile.mkdtemp(prefix="hedgemony-board-")
    pairs = [("clean_source", "generated_contracts_hold.py"),
             ("logic_source", "generated_with_contracts.py"),
             ("naming_source", "generated_sample.py")]
    for folder, fixture in pairs:
        os.makedirs(os.path.join(root, folder))
        shutil.copy(os.path.join(EXAMPLES, fixture), os.path.join(root, folder))
    return root, [os.path.join(root, f) for f, _ in pairs]


def main():
    print("\nORDERING\n")

    root, folders = build()
    sources = rank(folders)
    order = [s.label for s in sources]

    check("the source with everything holding ranks first",
          order[0] == "clean_source", " > ".join(order))
    check("a source with broken contracts ranks BELOW one where they hold",
          order.index("logic_source") > order.index("clean_source"),
          "the ordering bug this suite exists to prevent")
    check("a source with invented names ranks last here",
          order[-1] == "naming_source")

    by_label = {s.label: s for s in sources}
    check("broken contracts count as defects even with zero invented names",
          by_label["logic_source"].fabrications == 0
          and by_label["logic_source"].defects > 0,
          f"0 names, {by_label['logic_source'].defects} defect(s)")
    check("a clean source has no defects at all",
          by_label["clean_source"].defects == 0
          and by_label["clean_source"].examples > 0,
          f"{by_label['clean_source'].examples} example(s) held")

    print("\nTHE NUMBERS\n")

    for source in sources:
        print(f"    {source.label:<16} {source.defect_rate:>5.1f} per 100  "
              f"({source.fabrications} name(s), {source.contracts_broken} broken, "
              f"{source.lines} lines)")

    check("the rate is defects over lines",
          all(abs(s.defect_rate - (100.0 * s.defects / s.lines)) < 0.01
              for s in sources if s.lines))
    check("both components stay visible separately",
          all(hasattr(s, "fabrications") and hasattr(s, "contracts_broken") for s in sources),
          "a position is never a single opaque number")

    # Two sources at zero are not equally informative. The one that wrote more while staying
    # clean is the stronger result, and an empty directory must never win a board.
    empty = os.path.join(root, "empty_source")
    os.makedirs(empty)
    ranked = rank(folders + [empty])
    check("an empty source does not win the board",
          ranked[0].label != "empty_source", f"first is {ranked[0].label}")

    print("\nEVERY OUTPUT FORMAT\n")

    done = subprocess.run([sys.executable, "-m", "hedgemony", "--board", *folders, "--json"],
                          cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    payload = json.loads(done.stdout)
    check("--board --json returns one entry per source", len(payload) == 3)
    for field in ("label", "defect_rate", "fabrications", "contracts_broken", "lines", "files"):
        check(f"--board --json includes `{field}`", field in next(iter(payload.values())))

    markdown = render_board_markdown(sources)
    check("the markdown ranking is a table with every source",
          all(s.label in markdown for s in sources) and "| # |" in markdown)
    check("the markdown states the caveat about rewarding timidity",
          "not capability" in markdown)

    page = render_board_html(sources)
    check("the html ranking lists every source", all(s.label in page for s in sources))
    check("the ranking page uses the same design as a file report",
          "background:#000" in page.replace(" ", "") and 'class="wrap"' in page,
          "same ground, type and colours")
    check("the ranking page loads nothing external",
          "http://" not in page and "https://" not in page)
    check("the ranking page states the caveat", "not capability" in page)

    done = subprocess.run([sys.executable, "-m", "hedgemony", "--board", *folders,
                           "--no-colour"], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    check("the terminal ranking prints without escape codes",
          "\033[" not in done.stdout and "RANKED" in done.stdout)
    check("no column runs into the next one",
          not any("  " not in line[20:] for line in done.stdout.splitlines()
                  if line.strip().startswith(("1 ", "2 ", "3 "))),
          "columns stay separated")

    out = os.path.join(root, "ranking.html")
    subprocess.run([sys.executable, "-m", "hedgemony", "--board", *folders, "--out", out],
                   cwd=ROOT, capture_output=True, text=True,
                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    check("--out writes where asked and the extension picks the format",
          os.path.exists(out) and "<!doctype html>" in open(out).read())

    print("\nEDGE CASES\n")

    done = subprocess.run([sys.executable, "-m", "hedgemony", "--board",
                           os.path.join(EXAMPLES, "broken.py")],
                          cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    check("--board with a file rather than a directory says so and exits 2",
          done.returncode == 2, done.stderr.strip()[:60])

    single = rank([folders[0]])
    check("a single source still ranks without error", len(single) == 1)

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
