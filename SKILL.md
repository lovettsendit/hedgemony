---
name: hedgemony
description: Check generated code for names that do not exist — invented packages, modules, attributes, keywords and argument counts — and for code that contradicts its own stated examples. Every verdict comes from the interpreter or a package registry, never from a language model. Use after writing or reviewing code that touches any library, before presenting it.
---

# hedgemony

Find what was made up. Six classes of invented name plus contract violations, all decided by
the interpreter — no model is consulted, so a finding is a fact.

## Run it

```bash
hedgemony app.py              # one file
hedgemony src/                # a directory
hedgemony src/ --json         # parse this in a pipeline
hedgemony app.py --report md  # annotated copy of the file beside it
hedgemony app.py --no-run     # never run the checked file
hedgemony app.py --online     # also ask registries about uninstalled packages
hedgemony app.py --report both     # markdown and a page
hedgemony --board a/ b/ c/         # rank directories by defects per 100 lines
```

`--board` compares directories — two models, two strategies, before and after — by defects per
100 lines, counting invented names *and* failed examples. Nothing is generated and no model is
contacted. Read the line counts alongside the rate: a source that attempted less scores better
for it.

Exit **0** clean · **1** findings · **2** could not run.

## Act on what comes back

```
line   12  ATTR      `console` has no attribute `table`
line   11  CONTRACT  `pages_needed(10, 3)` was stated to give `4` but gave `3`
```

| class | action |
|---|---|
| `PACKAGE` | **rewrite.** The package was never published. Do not try to install it. |
| `MODPATH` | **rewrite** the import path. The package is real, the submodule is not. |
| `IMPORT` | **rewrite.** The module is real and does not export that name. |
| `ATTR` | **rewrite.** The object has no such attribute. |
| `KWARG` | **fix the call.** The function is real, the keyword is not. One line. |
| `ARITY` | **fix the call.** The function is real, the argument count is not. One line. |
| `CONTRACT` | **read both sides.** Code and its stated example disagree; either may be wrong. |

`PACKAGE MODPATH IMPORT ATTR` → the thing does not exist, the approach is wrong.
`KWARG ARITY` → the call is wrong, cheap fix.

## Name findings precisely

| word | means | decidable |
|---|---|---|
| **fabrication** | umbrella: a claim about the world that is false | yes |
| **invention** | the name exists nowhere | yes |
| **misattribution** | a real name on the wrong owner | yes |
| **malformation** | real target, impossible call | yes |
| **contradiction** | code disagrees with its own stated example | yes |
| **confabulation** | plausible wrong logic, nothing stated to check it | **no — not detected** |

Never say the model **lied** — lying requires intent, a model has none; report truth value
only. Never say **"no hallucinations found"** — say *no fabricated names found*, because
confabulation is invisible to every check here.

## Four things to get right

**1. Clean is not correct.** `0 fabrications` means every name exists. The code can still be
entirely wrong. Say "no fabricated names," never "verified" or "correct."

**1b. `NOT CHECKED` means blind, not clean.** A package that is not installed cannot be asked
about. hedgemony runs the scan inside the interpreter that owns the code — a `.venv` beside it
is found automatically, or use `--python /path/to/.venv/bin/python`. If `unchecked_imports` is
non-empty, never report the file as clean; name the packages that went unexamined.

**2. `NO_CONTRACT` and `UNCHECKED` are unknown, not pass.** If a file states no `>>>` examples,
its behaviour was never checked. Add one — it costs a line and makes behaviour checkable:

```python
def pages_needed(items, per_page):
    """
    >>> pages_needed(10, 3)
    4
    """
```

Write the example alongside every function you generate.

**3. The rate is a stopping signal.** Above roughly **3 fabrications per 100 lines**, stop
fixing findings one by one — the output is unreliable about that library as a whole. Read the
real API or escalate.

**4. `PACKAGE` vs "not installed" are different problems.** A type checker reports both as
"cannot find module." Only `hedgemony --online` separates *real but absent* (install it) from
*never existed* (rewrite it). Getting this backwards wastes a turn.

## Safety

Contract checking executes the file; everything else is static. Execution happens in a
separate, bounded interpreter — limited CPU, memory, processes, file size and wall time, no
network, stripped environment, temporary directory deleted after. A file with **no stated
examples is never executed at all**. `--no-run` runs no checked file at all.

The checked file is what is bounded. Deciding whether a name exists means importing the
module that would answer, so the file's **dependencies are imported** even under `--no-run`,
and an import with side effects performs them. That is the cost of asking the interpreter
instead of guessing.

This bounds accidents, not attackers. For code that may be hostile rather than merely wrong,
run the tool inside a container.

Network is **off by default**: the package names looked up come from generated code, so
`--online` is opt-in.

## Liability

Provided **as is, without warranty**. The sandbox limits accidents; it is not a security
boundary against deliberate escape, and no liability is accepted for containment failure.
For possibly-hostile code use `--no-run` (runs no checked file) or a container. LICENSE §15–17.

## Reading `--json`

```json
{"app.py": {"lines": 21, "rate": 9.52,
            "findings": [{"line": 12, "kind": "ATTR", "token": "console.table",
                          "detail": "`console` has no attribute `table`"}],
            "contracts": {"status": "NO_CONTRACT", "examples": 0,
                          "findings": [], "error": null}}}
```

`contracts.status` is one of `OK`, `VIOLATED`, `NO_CONTRACT`, `UNCHECKED`, `SKIPPED`.
Only `OK` means behaviour was checked and held.
