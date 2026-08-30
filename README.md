```
██╗  ██╗███████╗██████╗  ██████╗ ███████╗███╗   ███╗ ██████╗ ███╗   ██╗██╗   ██╗
██║  ██║██╔════╝██╔══██╗██╔════╝ ██╔════╝████╗ ████║██╔═══██╗████╗  ██║╚██╗ ██╔╝
███████║█████╗  ██║  ██║██║  ███╗█████╗  ██╔████╔██║██║   ██║██╔██╗ ██║ ╚████╔╝
██╔══██║██╔══╝  ██║  ██║██║   ██║██╔══╝  ██║╚██╔╝██║██║   ██║██║╚██╗██║  ╚██╔╝
██║  ██║███████╗██████╔╝╚██████╔╝███████╗██║ ╚═╝ ██║╚██████╔╝██║ ╚████║   ██║
╚═╝  ╚═╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝

────────────────────────────────────────────────────────────────────────────────
  F I N D   W H A T   W A S   M A D E   U P
────────────────────────────────────────────────────────────────────────────────
```

**hedgemony** finds the things that do not exist in code an AI wrote — packages that were never
published, methods that were never written, arguments no function accepts — and the code that
contradicts its own stated examples.

Every verdict comes from the Python interpreter or a package registry. **No language model is
asked anything.** That is the point: a finding is a fact about the world, not a second opinion
from the same kind of system that produced the mistake.

```
$ hedgemony dashboard.py

  dashboard.py
    2 fabrication(s) in 21 lines = 9.5 per 100 lines
    no stated examples in this file, so its behaviour was not checked at all

    line   12  ATTR      `console` has no attribute `table`
    line   19  ATTR      `console` has no attribute `progress`

    rewrite -- that attribute does not exist
```

---

## What the words actually mean

"Hallucination" is vague and "lying" is wrong, so hedgemony does not use either as a verdict.
Every finding is named precisely, and each name is a claim you can check:

| word | what it means | example | decidable? |
|---|---|---|---|
| **fabrication** | the umbrella: a claim about the world that is **false** | — | yes |
| **invention** | the name exists **nowhere** | `import ghostlib` | yes |
| **misattribution** | a **real** name on the **wrong** owner | `json.serialise` | yes |
| **malformation** | the target is real, the **call is impossible** | `math.sqrt(2, 3)` | yes |
| **contradiction** | the code disagrees with its **own stated behaviour** | a docstring example that fails | yes |
| **confabulation** | plausible wrong logic, with **nothing stated** to check it against | — | **no — not detected** |

Two words this tool deliberately avoids:

**"Lying" is the wrong word.** Lying requires intent to deceive. A model has no intent, so
nothing here takes a position on motive. hedgemony reports **truth value only**: this name does
not exist, this example did not hold. Whether anything meant to mislead is not a question the
interpreter can answer, and not one this tool pretends to.

**"Hallucination" is a popular umbrella** covering both the decidable and the undecidable.
hedgemony measures **only the decidable part** — the first five rows above. That is why a clean
result is reported as *no fabricated names*, never as *correct*.

### Why confabulation is not detected, and what to do about it

To say code is wrong, you need something to compare it against. hedgemony has two such
standards: the **interpreter**, for whether a name exists, and **an example you wrote**, for
whether the code does what you said. Confabulation has neither.

```python
def average(values):
    return sum(values) / len(values) - 1        # the -1 is wrong
```

Every name exists. Nothing states what the answer should be. The only description of what this
function does *is the function*, and it agrees with itself perfectly. There is nothing to check
it against — not by this tool, and not by any tool.

**It is not permanently invisible.** One line changes it:

```python
def average(values):
    """
    >>> average([2, 4])
    3.0
    """
    return sum(values) / len(values) - 1
```

```
line 3  CONTRACT  `average([2, 4])` was stated to give `3.0` but gave `2.0`
```

The confabulation became a **contradiction**, and contradictions are caught. This is exactly
why hedgemony reports `NO_CONTRACT` loudly instead of passing such files quietly — it is
telling you the one thing that would make the file checkable.

**Why no better tool fixes this.** "Is this what you meant?" is not a property of the code. It
exists only in your head until you write it down, and no amount of analysis can read an
intention that was never recorded. So the honest goal is not to detect intent — it is to make
*stating* intent cost one line, then execute it without mercy. That is what the contract layer
does, and it is why this gap is named here rather than left out.

---

## How it works

Two passes over each file. The first never runs anything; the second runs only what you wrote
down.

**Pass one — does this name exist?** The file is parsed into a syntax tree, and every name it
refers to becomes a question put to a live interpreter. Does `math` have `median`? Does `json`
export `serialise`? Does `re.sub` take a `greedy` keyword? These are answered with
`hasattr` and `inspect.signature` — the same machinery Python itself uses — so an answer is a
fact about the machine that will run your code, not an inference. Nothing is executed: asking
whether a name exists never requires calling it.

**Pass two — does the code do what it says?** If a docstring contains a `>>>` example, that
example is a claim the author wrote down, and running it settles whether the code agrees with
it. This is the only part that executes anything, it happens in a bounded separate process, and
**a file with no stated examples is never run at all** — that is decided by parsing, before
anything starts.

**When it cannot decide, it says nothing.** An uninstalled package, a variable whose type is
ambiguous, a C builtin with no readable signature — all produce silence rather than a guess.
That asymmetry is deliberate: a false alarm sends you to rewrite correct code and you have no
way to discover the tool was wrong, while a miss still meets every test and review downstream.

```
        your file
            │
            ├── parse ──► every name it claims exists
            │                     │
            │                     ▼
            │            ask the interpreter  ──►  exists / does not / cannot tell
            │                                          │        │           │
            │                                       silent   FINDING     NOT CHECKED
            │
            └── any ">>>" examples? ──no──► NO_CONTRACT (behaviour unknown)
                        │
                       yes
                        ▼
                run them, sandboxed  ──►  held / did not hold
```

That is the whole design. There is no model in it, no scoring, and no threshold to tune.

---

## Install

```bash
pip install hedgemony
```

Or just clone it and run — **there are no dependencies.** Python 3.9 or newer, standard library
only, nothing to configure.

```bash
git clone https://github.com/lovettsendit/hedgemony
cd hedgemony
python3 -m hedgemony yourfile.py
```

---

## Use

```bash
hedgemony app.py                  # one file
hedgemony src/                    # a directory, recursively
hedgemony src/ --quiet            # only show files with problems
hedgemony app.py --report         # write an annotated copy beside the file
hedgemony app.py --report html    # ...as a self-contained page instead
hedgemony src/ --json             # machine-readable, for a pipeline
hedgemony app.py --report both    # one of each
hedgemony app.py --no-run         # never run the checked file
hedgemony app.py --online         # also ask registries about uninstalled packages
hedgemony --board a/ b/ c/        # rank directories against each other
```

Exit codes: **0** nothing found · **1** findings · **2** the tool could not run. Drop it into
CI as-is.

---

## What it catches

Six kinds of invented name, each decided by asking the interpreter directly:

```
PACKAGE   import ghostlib               no such package was ever published
MODPATH   from json.fast import load    json is real, json.fast is not
IMPORT    from json import serialise    json exists and does not export that
ATTR      console.table(...)            the object has no such attribute
KWARG     re.sub(..., greedy=True)      the function accepts no such keyword
ARITY     math.sqrt(2, 3)               the function cannot take that many arguments
```

They split into exactly two actions, which is the part that saves time:

| | meaning | what to do |
|---|---|---|
| `PACKAGE` `MODPATH` `IMPORT` `ATTR` | the thing does not exist | **rewrite** |
| `KWARG` `ARITY` | the function is real, the call is wrong | **fix the call** |

### The distinction other tools cannot make

A type checker gives the same error for both of these:

```python
from humanize import naturalsize   # a real package — just not installed here
import ghostlib                     # never existed anywhere
```

> `Cannot find implementation or library stub for module named "humanize"`
> `Cannot find implementation or library stub for module named "ghostlib"`

Same message, completely different problem. One is `pip install`. The other means the code can
never work and needs rewriting. `hedgemony --online` tells them apart:

```
line 2  PACKAGE  no package `ghostlib` was ever published
```

`humanize` is not flagged. It exists.

---

## What it catches that has nothing to do with names

Names existing is not the same as code being right:

```python
def pages_needed(items, per_page):
    """How many pages are needed to show every item.

    >>> pages_needed(10, 3)
    4
    """
    return math.floor(items / per_page)
```

`math.floor` exists. The call is well formed. Every static checker passes this file — and it is
wrong. Ten items at three per page needs four pages; this returns three.

```
line   11  CONTRACT  `pages_needed(10, 3)` was stated to give `4` but gave `3`
```

The authority is not this tool's opinion about what the function should do. It is a claim the
author wrote into the file, in a standard executable format. hedgemony reports the contradiction
between two things already in the file — and does **not** guess which side is wrong.

**Making a file checkable costs one line.** If a file states no examples, hedgemony says so plainly
rather than passing it:

```
no stated examples in this file, so its behaviour was not checked at all
```

---

## What it does not do

This matters more than the feature list.

- **A clean result is not a proof of correctness.** It means no fabricated *name* was found.
  Code that calls the wrong real function is invisible to name checking, by construction. Every
  report says so in those words.
- **It does not judge style, performance, or design.**
- **It does not guess.** Anything that cannot be decided — an uninstalled package's internals,
  a variable of ambiguous type, a C builtin with no introspectable signature — is left
  unreported. A false alarm sends someone to rewrite correct code with no way to discover the
  tool was wrong; a miss still meets every test downstream. The costs are not symmetric, so
  ambiguity always resolves to silence.

---

## Reports

```bash
hedgemony app.py --report        # app.py.hedgemony.md
hedgemony app.py --report html   # app.py.hedgemony.html
```

One report per source file, at one fixed name, **overwritten every run** — a hundred runs leave
one file, not a hundred.

The markdown carries the whole file with every line marked and each finding keyed by number.
It reads correctly as plain text, needs no renderer, and compresses well, which matters when
the reader is an agent paying for every line:

```
+  8 | def pages_needed(items, per_page):
+  9 |     """How many pages are needed to show every item.
+ 10 |
! 11 |     >>> pages_needed(10, 3)  #1
+ 12 |     4
+ 13 |     """
+ 14 |     return math.floor(items / per_page)
```

The HTML is one self-contained page — black ground, code coloured green where it is clean and
red where it is not, nothing loaded from anywhere.

### Choosing what gets written

```bash
hedgemony app.py --report        # markdown  (default)
hedgemony app.py --report html   # a page
hedgemony app.py --report both   # one of each
```

Nothing is written unless you ask. Without `--report` it prints to the terminal and leaves no
files behind.

---

## Using this with your local model

**hedgemony never talks to your model.** There is no endpoint to configure, no API key, no
integration with any runner. It works on the code your model produced, which is already a file
on disk. That is deliberate: a checker that asked the model whether the model was wrong would
be asking the thing that made the mistake, and its answer would be worth nothing. The
interpreter has no such conflict of interest.

So the flow is three steps, and the first two are what you already do:

```
  1.  your model writes code       (any runner, any IDE, any agent — it does not matter)
  2.  it lands in a file           (this already happens)
  3.  hedgemony thatfile.py        ← the only new step
```

```bash
# whatever you normally do to get code out of your model, then:
hedgemony generated.py
```

That works for **any** model — local, hosted, one you have no API access to, or a snippet
someone sent you. If it produced code you can save, hedgemony can check it.

### Comparing models

Give each model its own folder and rank them:

```
  out/
    qwen/       ← one model's output
    llama/      ← another's
    handwritten/
```

```bash
hedgemony --board out/qwen out/llama out/handwritten
```

```
  RANKED BY DEFECTS PER 100 LINES  (lower is better)

     source                  per 100  names     contracts   lines  files
  1  handwritten                 0.0      0        4 held      34      1
  2  llama                       3.3      0      2 broken      61      1
  3  qwen                        9.5      2   none stated      21      1
```

Same prompts into each folder makes it a fair comparison. Read the line counts alongside the
rate — a model that wrote less scores better for it.

### Getting more out of it

Ask your model to include a `>>>` example in each docstring. It costs one line, models produce
them readily, and it turns behaviour from unknown into checkable:

> "…and give every function a docstring with a `>>>` example showing the expected output."

Without one, hedgemony can only tell you the names exist. With one, it can tell you the code
disagrees with what the model itself said it would do — which is how the logic bug in
`examples/generated_with_contracts.py` was caught.

---

## Ranking sources against each other

One measurement is an anecdote. A rate over a body of code is comparable.

```bash
hedgemony --board out/model_a out/model_b out/handwritten
```

```
  RANKED BY DEFECTS PER 100 LINES  (lower is better)

     source                  per 100  names     contracts   lines  files
  1  handwritten                 0.0      0        4 held      34      1
  2  model_b                     3.3      0      2 broken      61      1
  3  model_a                     9.5      2   none stated      21      1
      1x  `console` has no attribute `table`
      1x  `console` has no attribute `progress`
```

A source is just a directory, so this compares whatever you put in them — two models, two
prompting strategies, last month against this month, your team against a vendor. **Nothing is
generated and no model is contacted**; it reads code that already exists, which is why it can
score anything you can save to disk.

The rank is over **every** defect found — invented names *and* stated examples that failed.
Ranking on names alone once put a source with two broken contracts above one where four held,
because neither had invented anything. Both columns stay visible so a position is never a
single opaque number.

```bash
hedgemony --board a/ b/ --out board.html   # the extension picks the format
hedgemony --board a/ b/ --json             # for a pipeline
```

**Read the line counts.** A rate measures defects, not capability, and a source that attempted
less will score better for it. That caveat is printed with every ranking rather than left in
the documentation.

---

## It does not have to live where your code lives

Every verdict comes from asking an interpreter whether a name exists — so **which** interpreter
is asked decides the answer. Install hedgemony on its own and it cannot see your project's
libraries:

```
$ hedgemony app.py
    0 fabrication(s) in 21 lines = 0.0 per 100 lines
    NOT CHECKED: rich — not installed in the interpreter used, so names from it
                 were not examined
```

Zero findings, because nothing could be looked at. Silence that reads like a pass is the worst
failure a checker can have, so hedgemony does two things about it.

**It says so.** Any package it could not resolve is listed as `NOT CHECKED`, by name.

**It goes and asks your interpreter instead.** hedgemony depends on nothing outside the
standard library, so it can run inside your project's environment without being installed
there. A virtual environment beside your code is found automatically:

```
$ hedgemony app.py
  using the interpreter that owns this code: Python 3.12 at /path/to/project/.venv

    2 fabrication(s) in 21 lines = 9.5 per 100 lines
    line 12  ATTR  `console` has no attribute `table`
```

Same tool, same file, one install — it just asked the right interpreter. Point it anywhere:

```bash
hedgemony src/ --python /path/to/project/.venv/bin/python
hedgemony src/ --python self      # force the interpreter running hedgemony
```

The order it chooses: `--python` if given, then a `.venv`/`venv`/`.env` found by walking up
from your code, then an activated `VIRTUAL_ENV`, then the interpreter running hedgemony. When
it hands over, it prints which interpreter it used — that is never silent.

If the interpreter you point it at cannot run the scan — too old, missing a module, not really
an interpreter — hedgemony says so and **falls back to its own**, listing whatever it cannot
resolve as `NOT CHECKED`. A partial answer with the gaps named beats no answer at all.

Only hedgemony's own package is copied across, never the environment it was installed into. If
it shared its own `site-packages`, your project would appear to have libraries it does not
have, and the tool would go quiet for the wrong reason.

---

## macOS: the `._` files

If you keep code on an exFAT or FAT32 drive, an SD card, or most network shares, macOS writes a
hidden metadata companion for every file — `app.py` gets a `._app.py` alongside it. They match
every source glob and are not source.

**hedgemony skips them by name, everywhere**, so you do not need to do anything. If you want
them gone from a checkout:

```bash
dot_clean .                      # merge and remove them
find . -name '._*' -delete       # or just delete them
```

The bundled `.gitignore` already excludes `._*` and `.DS_Store` so they never reach a commit.

---

## Safety

Contract checking has to run the file, and the file was written by a machine. So:

- Every execution happens in **a separate interpreter**, bounded on CPU, memory, process count,
  file size and wall time.
- **Network is refused** inside that interpreter.
- **The environment is stripped** — your tokens and keys are not visible to executed code.
- It runs in a **temporary directory that is deleted afterwards**.
- **A file with no stated examples is never executed at all.** That is decided by parsing.
- **`--no-run`** never runs the checked file.
- **Its dependencies are still imported**, under every mode. Deciding whether a name exists
  means importing the module that would answer, and importing anything runs that module's
  top-level code. A dependency with import-time side effects will perform them. This is the
  price of asking the interpreter rather than guessing from a stub, and it is why the answers
  are facts — but it is not "nothing executes", and saying so would be exactly the kind of
  overstatement this tool exists to catch.
- Registry lookups are **off by default**, because the package names being looked up come from
  generated code.

Memory is not left to the kernel. On macOS, `RLIMIT_AS`, `RLIMIT_DATA` and `RLIMIT_RSS` were
all measured taking a 200 MB allocation under a 64 MB cap without complaint, and a guard whose
behaviour depends on which machine it runs on is not a guard. So the ceiling is enforced from
both sides: the parent samples the whole process group (the only view that sees child processes
or a wedged run), and the child checks its own usage far more often than the parent can afford
to. Together they stop a 200 MB block allocated and dropped six times over in under a third of
a second.

**This bounds accidents, not attackers.** Real isolation against code deliberately trying to
escape needs a container, and this tool does not claim otherwise. If what you are checking may
be hostile rather than merely wrong, run hedgemony inside one.

---

## Evidence

Run it yourself:

```bash
python3 tests/run_all.py
```

Nine suites, no test framework required, no network needed. `tests/test_proof.py` argues the
central claim four independent ways, and prints its working:

**Ground truth comes from the interpreter, not from hedgemony.** Ten names, labelled real or
invented before anything runs:

```
                              flagged   not flagged
  invented (should flag)        4             0
  real     (should not)         0             6

  recall     1.00   (4 of 4 invented names caught)
  precision  1.00   (4 of 4 flags were genuinely invented)
  false alarms on real names: 0 of 6
```

**The world confirms it by failing.** The flagged call is executed:

```
  hedgemony said : `console` has no attribute `table`
  running it : AttributeError -- 'Console' object has no attribute 'table'
```

**Nothing was asked.** The same scan is repeated with the network unavailable and produces
identical findings — no service, endpoint or model contributed to the verdict. This is what
separates hedgemony from confidence scores and self-consistency checks, which ask the model that
made the mistake whether it made a mistake.

**The samples are real.** Every file in `examples/` beginning `generated_` is unmodified output
from a small local code model, saved exactly as produced. Nothing about them was arranged to be
catchable.

**And the two layers catch different things.** This is the result worth reading twice —
generated code with **zero** invented names, which every name checker and every type checker
passes clean:

```
  generated_with_contracts.py
    0 fabrication(s) in 61 lines = 0.0 per 100 lines
    2 of 5 stated example(s) did not hold

    line 61  CONTRACT  `format_byte_count(1024)` was stated to give `'1.0 KB'` but gave `'0.0 MB'`
    line 63  CONTRACT  `format_byte_count(1536)` was stated to give `'1.5 KB'` but gave `'0.0 MB'`
```

Every name in that file exists. The function is real, the call is well formed, and it is
wrong — it always returns megabytes and divides by the wrong constant, so one megabyte reports
as `'1024.0 MB'`. Name checking alone exits 0 on this file. The model's own stated example is
what proves the bug.

`examples/generated_contracts_hold.py` is the negative control: also generated, also unmodified,
and completely fine — four stated examples, all of which hold. A suite where every fixture
fails cannot tell a working detector from one that flags everything.

`tests/test_sandbox.py` tests every containment guard with code written to defeat that specific
guard — infinite loops, runaway allocation, forking, oversized writes, outbound connections,
environment leakage. One rule governs those payloads: each is harmless if the guard it tests
fails.

---

## For agents

`hedgemony` is built to be called by an agent inside its own loop, on its own output, before code
reaches a person.

- **`AGENT.md`** — how to read every class, what action each one implies, when to escalate.
- **`SKILL.md`** — a drop-in skill definition.

The short version: parse `--json`, treat `PACKAGE`/`IMPORT`/`ATTR` as *rewrite* and
`KWARG`/`ARITY` as *fix the call*, never report a clean scan as "correct", and above roughly
**3 fabrications per 100 lines** stop patching findings one at a time and go read the real API.

---

## Disclaimer — read this before running it on untrusted code

**THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT.** See sections 15, 16 and 17 of the [LICENSE](LICENSE) for the
binding text. The following is a plain-language summary of what that means here; the licence
governs.

**The sandbox is a blast-radius limiter, not a security boundary.** Checking contracts means
running code. hedgemony bounds that run — separate process, CPU and memory ceilings, a process
cap, a file-size cap, refused sockets, a stripped environment, a temporary directory that is
deleted — and every one of those guards is tested against code written to defeat it. None of
that makes it safe against code that is *deliberately* trying to escape. It is designed to keep
accidents small, and it says so rather than claiming more.

**Specifically not warranted or defended against:**

- code that deliberately attempts to escape process isolation
- code that reads or exfiltrates files your user account can already read
- code that calls out to the operating system to do what the in-process guards refuse
- resource exhaustion faster than the guards can observe it
- platform behaviour outside this project's control — on macOS, for instance, **no kernel
  memory limit is enforced at all**, which is why memory is bounded in software instead

**No liability is accepted for any security breach, data loss, resource exhaustion, or failure
of the sandbox to contain anything**, whether arising from use of this software, from its
guards behaving other than described, or from any defect in it. You run it at your own risk.

**If the code you are checking may be hostile rather than merely wrong**, do not rely on these
guards. Run hedgemony inside a container, a virtual machine, or a throwaway account with no
access to anything you care about. For that case use `--no-run`, which never runs the file
and reduces hedgemony to pure static analysis:

```bash
hedgemony suspicious/ --no-run
```

`--no-run` is the lowest-risk mode: the checked file never runs. It is not zero execution,
because the file's dependencies are still imported in order to answer questions about them.
If even that is too much, do not point the tool at the code.

---

## License

[Server Side Public License v1](LICENSE) (SSPL-1.0).

Free to use, modify and self-host. If you offer hedgemony to third parties as a service, the SSPL
requires you to release the source of the service under the same terms.

SSPL is not OSI-approved, and some organisations disallow it by policy. That is a deliberate
trade for the service clause.
