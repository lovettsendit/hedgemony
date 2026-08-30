# hedgemony — guide for an agent

You are an agent that writes or reviews code. `hedgemony` tells you which names in that code do not
exist, and which code contradicts its own stated examples. Every verdict comes from the Python
interpreter or a package registry. **No language model is consulted at any point**, which is
what makes a finding a fact rather than a second opinion.

---

## 1. The one rule that prevents harm

**A clean result is not a proof of correctness.** It means no fabricated *name* was found.

```
0 fabrications in 40 lines        <- every name exists
                                  <- the code may still be completely wrong
```

Never report "hedgemony passed, the code is correct." Report "no fabricated names; behaviour
unchecked" unless contracts also ran and held. Treating silence as approval is the only way
this tool makes things worse.

---

## 1b. Use these words, not "hallucination" or "lying"

When you report a finding to a person, name it precisely. Both popular words are imprecise and
one is simply wrong.

| word | means | decidable |
|---|---|---|
| **fabrication** | umbrella: a claim about the world that is false | yes |
| **invention** | the name exists nowhere (`import ghostlib`) | yes |
| **misattribution** | a real name on the wrong owner (`json.serialise`) | yes |
| **malformation** | real target, impossible call (`sqrt(2, 3)`) | yes |
| **contradiction** | code disagrees with its own stated example | yes |
| **confabulation** | plausible wrong logic, nothing stated to check it | **no — not detected** |

**Never say the model "lied."** Lying requires intent; a model has none. Report truth value:
*this name does not exist*, *this example did not hold*. Do not attribute motive.

**Never say "no hallucinations found."** Say *no fabricated names found*. Confabulation — the
last row — is invisible to every check here, so a clean scan is silent about it rather than
clearing it.

---

## 2. When to run it

| situation | run |
|---|---|
| you just wrote code using a library you are not certain about | always |
| you are about to hand code to a user | always |
| a dependency failed to import and you must decide install-vs-rewrite | always |
| you are reviewing code someone else generated | always |
| you changed only comments, strings, or formatting | skip |

Run it **before** you present code, not after the user reports a failure.

---

## 3. Reading the output

```
hedgemony app.py
```

```
  app.py
    2 fabrication(s) in 21 lines = 9.5 per 100 lines
    no stated examples in this file, so its behaviour was not checked at all

    line   12  ATTR      `console` has no attribute `table`
    line   19  ATTR      `console` has no attribute `progress`
```

### The six name classes split into exactly two actions

| class | means | your action |
|---|---|---|
| `PACKAGE` | no such package was ever published | **rewrite** — do not try to install it |
| `MODPATH` | the package is real, that submodule is not | **rewrite** the import path |
| `IMPORT` | the module is real, it does not export that name | **rewrite** — find the real name |
| `ATTR` | the object has no such attribute | **rewrite** — find the real method |
| `KWARG` | the function is real, that keyword is not | **fix the call** — cheap |
| `ARITY` | the function is real, that argument count is not | **fix the call** — cheap |

The split is the useful part. `PACKAGE`/`MODPATH`/`IMPORT`/`ATTR` mean *the thing does not
exist* — the design is wrong. `KWARG`/`ARITY` mean *the call is wrong* — a one-line fix.

### The distinction nothing else gives you

A type checker reports the same error for both of these:

```
from humanize import naturalsize     # real package, not installed here
import ghostlib                       # never existed
```

`hedgemony --online` separates them. `humanize` → **install it**. `ghostlib` → **rewrite, it is
imaginary.** Getting this backwards wastes a turn either way.

### The seventh class: `CONTRACT`

```
line   11  CONTRACT  `pages_needed(10, 3)` was stated to give `4` but gave `3`
```

Every name exists. The code contradicts an example written in its own docstring. The tool does
**not** know which side is wrong — the docstring may be the mistake. Read both, decide, fix
one. Never silently change the docstring to match the code; that erases the evidence.

---

## 3b. `NOT CHECKED` means blind, not clean

```
0 fabrication(s) in 21 lines = 0.0 per 100 lines
NOT CHECKED: rich — not installed in the interpreter used
```

Zero findings **because nothing could be looked at.** A package that is not installed cannot be
asked about, so every name reached through it went unexamined.

hedgemony handles this itself: it runs the scan inside the interpreter that owns the code,
finding a `.venv` beside it automatically, or wherever `--python` points. It does not need to
be installed in that environment.

```bash
hedgemony src/ --python /path/to/project/.venv/bin/python
```

**If you see `unchecked_imports` in the JSON and it is not empty, do not report the file as
clean.** Re-run against the right interpreter, or say plainly which packages went unexamined.

---

## 4. Contract states — two of them are not verdicts

| status | meaning | what you do |
|---|---|---|
| `OK` | every stated example held | behaviour is checked and holds |
| `VIOLATED` | an example did not hold | fix the code or the example |
| `NO_CONTRACT` | the file states nothing checkable | **behaviour is unknown** — add a `>>>` example |
| `UNCHECKED` | the run hit a limit or the file would not import | **behaviour is unknown** — investigate |

`NO_CONTRACT` and `UNCHECKED` are *unknown*, never *fine*. If you need behavioural assurance
and get either, you do not have it.

**Making a file checkable costs one line.** Add an example to the docstring:

```python
def pages_needed(items, per_page):
    """How many pages are needed to show every item.

    >>> pages_needed(10, 3)
    4
    """
```

That single line turns `NO_CONTRACT` into a real check. When you generate a function, generate
the example with it.

---

## 5. The rate is an escalation signal

`fabrications per 100 lines` is a scalar, so you can threshold on it:

| rate | reading | action |
|---|---|---|
| `0.0` | no invented names | proceed — behaviour still unverified |
| `0 < r ≤ 3` | isolated slips | fix them in place |
| `r > 3` | the model is guessing at this library | **stop patching.** Read the real API, or escalate to a stronger model |

Above roughly 3 per 100, fixing findings one at a time is usually the wrong move — the output
is unreliable about that library as a whole, and the next generation will invent something new.

---

## 6. Commands

```bash
hedgemony app.py                  # one file
hedgemony src/                    # a directory, recursively
hedgemony src/ --json             # machine-readable — parse this, not the text
hedgemony src/ --quiet            # only files with findings
hedgemony app.py --report md      # write a full annotated copy beside the file
hedgemony app.py --report html    # same, as a self-contained page
hedgemony app.py --no-run         # never run the checked file; names only
hedgemony app.py --online         # also ask registries about uninstalled packages
hedgemony app.py --report both    # one of each
hedgemony app.py --python PATH    # use the interpreter that owns the code
hedgemony --board a/ b/ c/        # rank directories by defects per 100 lines
hedgemony --board a/ b/ --out board.html   # the extension picks the format
```

Exit codes: **0** nothing found · **1** findings · **2** the tool could not run.

### `--board`

Ranks directories against each other by **defects per 100 lines** — invented names *plus*
stated examples that failed. Use it to compare two models, two prompting strategies, or the
same source over time. Nothing is generated and no model is contacted; it reads code already on
disk, so it scores whatever you save into folders.

Read the line counts with the rate. A source that attempted less scores better for it, and the
rate measures defects, not capability.

### JSON shape

```json
{
  "app.py": {
    "language": "python",
    "lines": 21,
    "rate": 9.52,
    "findings": [
      {"line": 12, "kind": "ATTR", "token": "console.table",
       "detail": "`console` has no attribute `table`"}
    ],
    "unchecked_imports": ["rich"],
    "contracts": {"status": "NO_CONTRACT", "examples": 0, "findings": [], "error": null}
  }
}
```

`unchecked_imports` lists packages the interpreter did not have. **Anything named there went
unexamined** — do not report the file as clean while that list is non-empty.

---

## 7. Safety — what running this does to the machine

Checking contracts means **executing the file**. Everything else is decided by parsing it.

One thing does run either way, and it is stated plainly because the distinction matters:
deciding whether `json` exports `serialise` means importing `json`, and importing any module
runs that module's top-level code. So **the checked file's dependencies are imported**, and a
dependency with import-time side effects will perform them. The checked file itself is not
run unless its contracts are being checked.

Every execution happens in a separate interpreter that is bounded on CPU, memory, process
count, file size and wall time, is refused network access, gets a stripped environment (your
tokens and keys are not visible to it), and works in a directory deleted afterwards.

- A file with **no stated examples is never executed at all** — that is decided by parsing.
- `--no-run` never runs the checked file. Its dependencies are still imported, as above.
- The default is **offline**. `--online` sends package *names* — which came from generated
  code — to a public registry. Consider that before enabling it in a loop.

This bounds accidents. It is **not** a security boundary against code deliberately trying to
escape. If the code may be hostile rather than merely wrong, run the whole tool in a container.

---

## 7b. Liability

This software is provided **as is, without warranty of any kind**. The sandbox limits the
blast radius of an accident; it is **not** a security boundary against code deliberately
trying to escape, and no liability is accepted for any breach or containment failure. If
the code may be hostile rather than merely wrong, use `--no-run` (which runs no checked file)
or run inside a container. See the LICENSE, sections 15–17.

---

## 8. Rules

- **R1** Run hedgemony before presenting generated code that touches a library.
- **R2** Never say "correct" on the basis of a clean scan. Say "no fabricated names."
- **R3** `PACKAGE` means rewrite, never install. `IMPORT`/`ATTR` mean the name is imaginary.
- **R4** `KWARG`/`ARITY` are cheap fixes — the function is real.
- **R5** On `CONTRACT`, read both sides. Never edit the docstring to match the code.
- **R6** Treat `NO_CONTRACT` and `UNCHECKED` as unknown, never as pass.
- **R7** Above ~3 per 100 lines, stop patching and go read the real API.
- **R8** Generate a `>>>` example with every function you write. It costs one line and it is
  the only thing that makes behaviour checkable.
- **R9** Parse `--json`. Do not scrape the human output.
- **R10** Leave `--online` off inside automated loops unless you need the package distinction.
