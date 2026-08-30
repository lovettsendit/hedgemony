"""Rank sources of code by how much of it does not exist.

WHY A RATE AND NOT A COUNT. One caught fabrication is an anecdote. Two hundred lines with four
fabrications and eight hundred lines with four are not the same thing, and only a rate says so.
Fabrications per hundred lines is what makes two directories -- two models, two versions, two
prompting strategies, last week and this week -- comparable at all.

WHAT A SOURCE IS. A directory. Point this at several and each is scored on its own, labelled by
its directory name. If the folders hold output from different models, this ranks models. If
they hold last month and this month, it ranks a change over time. If they hold one team's code
and a vendor's, it ranks those. Nothing here knows or cares which, because the measurement is
the same in every case.

NO MODEL IS CONTACTED, AND NOTHING IS GENERATED. This reads code that already exists on disk.
That is deliberate: a ranking tool that had to call an endpoint would need credentials, network
access and a configured provider before it could tell anybody anything, and it would only be
able to score models the person running it happened to have. Save output into folders and this
scores anything.

THE HONEST LIMITATION, WHICH THE OUTPUT ALSO STATES. A low rate can mean a source is careful,
or it can mean a source wrote less and attempted less. The rate measures fabrication, not
capability, and it will reward timidity if read alone. Line counts sit next to every rate so
that a source which scored well by saying very little is visible rather than hidden.
"""
from __future__ import annotations

import os

from .cli import collect
from .contracts import check_contracts
from .sandbox import Limits
from .scan import scan

__all__ = ["rank", "Source"]


class Source:
    """One scored collection of code."""

    __slots__ = ("label", "path", "files", "lines", "fabrications", "rate",
                 "contracts_checked", "contracts_broken", "examples", "top",
                 "defects", "defect_rate")

    def __init__(self, label, path):
        self.label = label
        self.path = path
        self.files = self.lines = self.fabrications = 0
        self.contracts_checked = self.contracts_broken = self.examples = 0
        self.rate = 0.0
        self.defects = 0
        self.defect_rate = 0.0
        self.top = []

    def as_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


def rank(paths, run_contracts=True, limits: Limits = None, interpreter=None, scans=None):
    """Score each path and return the sources ordered best first.

    Ties are broken by line count, longest first: two sources at zero are not equally
    informative, and the one that produced more code while staying clean is the stronger
    result. Without that rule an empty directory would win every board.

    `interpreter` and `scans` carry the environment the code actually belongs to: `scans` holds
    results already obtained there, and `interpreter` runs the contracts. They matter more here
    than anywhere else. A board scored against the wrong interpreter cannot see a project's
    libraries, so every name reached through one goes unexamined and the directory ranks CLEAN
    for the reason that should have disqualified it -- and unlike a single file report, a
    ranking gives the reader no obvious place to notice.
    """
    limits = limits or Limits()
    scans = scans or {}
    sources = []

    for path in paths:
        label = os.path.basename(os.path.abspath(path.rstrip(os.sep))) or path
        source = Source(label, path)
        counted = {}

        for filename in collect([path]):
            try:
                result = scans.get(filename) or scan(filename)
            except OSError:
                continue
            if "error" in result:
                continue
            source.files += 1
            source.lines += result["lines"]
            source.fabrications += len(result["findings"])
            for finding in result["findings"]:
                counted[finding["detail"]] = counted.get(finding["detail"], 0) + 1

            if run_contracts and result["language"] == "python":
                contract = check_contracts(filename, limits=limits, interpreter=interpreter)
                if contract.checked:
                    source.contracts_checked += 1
                    source.examples += contract.examples
                    source.contracts_broken += len(contract.findings)

        source.rate = (100.0 * source.fabrications / source.lines) if source.lines else 0.0
        # A BROKEN CONTRACT IS A DEFECT FOUND, and the ordering has to say so. Ranking on
        # fabrications alone put a source with two failing examples above one whose four
        # examples all held, purely because neither had invented a name -- which reads as an
        # endorsement of the worse code. The rank is therefore over everything this tool
        # actually found, and both components stay visible in their own columns so the reason
        # for a position is never hidden inside a single number.
        source.defects = source.fabrications + source.contracts_broken
        source.defect_rate = (100.0 * source.defects / source.lines) if source.lines else 0.0
        source.top = sorted(counted.items(), key=lambda kv: -kv[1])[:3]
        sources.append(source)

    return sorted(sources, key=lambda s: (s.defect_rate, -s.lines))
