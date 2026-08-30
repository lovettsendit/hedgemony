"""Does the scanner flag what is invented and stay silent on what is real?

BOTH DIRECTIONS ARE REQUIRED and either one alone is worthless:

    a checker that flags everything   catches every fabrication and is useless
    a checker that flags nothing      never false-alarms and is useless

So the silence cases come FIRST in this file. They are the ones that matter most: reporting a
real name as invented sends someone to rewrite correct code, and they have no way to discover
the tool was wrong. Several of the cases below are regressions -- code this tool genuinely
reported as fabricated before it was fixed -- and they are kept verbatim so the same mistake
cannot return quietly.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from hedgemony.scan import scan                              # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  [{'ok  ' if condition else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def kinds(source):
    return [f["kind"] for f in scan(source, language="python", is_source=True)["findings"]]


def silent(name, source):
    found = kinds(source)
    check(name, not found, "" if not found else f"FALSE ALARM: {found}")


def flags(name, source, expected):
    found = kinds(source)
    check(name, expected in found, f"got {found or 'nothing'}")


def main():
    print("\nSILENCE ON CORRECT CODE -- the direction that must never be wrong\n")

    silent("a plain correct file", "import math\nprint(math.sqrt(9))\n")

    # REGRESSION. `from X import Y` binds Y to X.Y, not to X. An earlier version resolved
    # `datetime` as the MODULE, asked whether the module had `fromisoformat`, and reported
    # correct code as fabricated.
    silent("`from datetime import datetime` then a class method",
           "from datetime import datetime\nstamp = datetime.fromisoformat('2020-01-01')\n")

    # REGRESSION. Counting only constructor-shaped assignments made a later rebinding
    # invisible, so methods were resolved against a class the variable no longer held.
    silent("a variable rebound to something else is not resolved",
           "from json import JSONEncoder\ne = JSONEncoder()\ne = 5\nprint(e.bit_length())\n")

    # A function declaring **kwargs accepts keywords that are not in its signature. Deciding
    # otherwise would flag correct calls across most of the standard library.
    silent("a function taking **kwargs accepts unlisted keywords",
           "import subprocess\nsubprocess.run(['ls'], capture_output=True)\n")

    # Many builtins are written in C and expose no introspectable signature. Unknown is not
    # a finding.
    silent("a builtin with no introspectable signature is left alone",
           "print(sorted([3, 1, 2], reverse=True))\n")

    silent("an uninstalled package is unknown, not invented",
           "import somepackagethatisnotinstalledhere\n")

    silent("an aliased import resolves to the real module",
           "import math as m\nprint(m.floor(2.5))\n")

    silent("a local variable of unknown type is not guessed at",
           "def f(thing):\n    return thing.whatever()\n")

    print("\nDETECTION -- one case per class, each decided by the interpreter\n")

    flags("ATTR   a module attribute that does not exist",
          "import math\nprint(math.median([1, 2, 3]))\n", "ATTR")

    flags("ATTR   a method that does not exist on a local object's class",
          "from json import JSONEncoder\ne = JSONEncoder()\nprint(e.encode_fast('x'))\n",
          "ATTR")

    flags("IMPORT a name the module does not export",
          "from json import serialise\n", "IMPORT")

    flags("KWARG  a keyword the function does not accept",
          "import re\nre.sub('a', 'b', 'aaa', greedy=True)\n", "KWARG")

    flags("ARITY  more positional arguments than the function takes",
          "import math\nprint(math.sqrt(2, 3))\n", "ARITY")

    flags("MODPATH a submodule that does not exist",
          "from json.nonexistent import thing\n", "MODPATH")

    print("\nRATE -- the number that makes two files comparable\n")

    clean = scan("import math\nprint(math.sqrt(9))\n", language="python", is_source=True)
    check("a clean file rates zero", clean["rate"] == 0.0, f"{clean['rate']:.1f} per 100")

    dirty = scan("import math\nprint(math.median([1]))\nprint(math.average([1]))\n",
                 language="python", is_source=True)
    check("a file with two fabrications in three lines rates above sixty",
          dirty["rate"] > 60, f"{dirty['rate']:.1f} per 100")

    check("findings arrive in line order",
          [f["line"] for f in dirty["findings"]] == sorted(f["line"] for f in dirty["findings"]))

    print("\nROBUSTNESS\n")

    check("a file that will not parse produces no findings, not a crash",
          kinds("def broken(:\n") == [])
    check("an empty file is handled", scan("", language="python", is_source=True)["lines"] == 0)

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
