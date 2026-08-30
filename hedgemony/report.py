"""Three ways to read the same findings: a terminal, an agent, and a person.

ONE FILE PER SOURCE FILE, ALWAYS OVERWRITTEN. A checker that leaves a timestamped artefact
behind on every run turns into a directory of near-identical files that nobody deletes. The
report for a source file has one fixed name derived from that file, so running the tool a
hundred times leaves one report holding the latest answer.

WHY MARKDOWN IS THE AGENT FORMAT. It carries the whole file with per-line marks and reads
correctly as plain text with no renderer, no styling and no escaping rules. It also compresses
well, which matters when the reader is paying for every line it takes in.

THE ONE THING EVERY FORMAT MUST SAY. A clean result means no fabricated NAME was found. It does
not mean the code is correct. Every renderer here states that in the output rather than leaving
it to be inferred, because silence that looks like approval is the way a checking tool does
real damage.
"""
from __future__ import annotations

import html
import os

from .scan import FabricationClass

__all__ = ["render_text", "render_markdown", "render_html", "write_report", "report_path",
           "render_board_text", "render_board_markdown", "render_board_html"]

CLEAN_NOTE = ("no fabricated names found -- this does NOT mean the code is correct, "
              "only that every name it refers to exists")
NO_CONTRACT_NOTE = ("no stated examples in this file, so its behaviour was not checked at all "
                    "-- add a `>>>` example to a docstring and it will be")


def report_path(source_path: str, extension: str) -> str:
    """The single fixed report location for a source file."""
    return f"{os.path.abspath(source_path)}.hedgemony.{extension}"


def _combine(scan_result, contract_result):
    """Findings from both layers in line order, with contract findings kept distinguishable."""
    findings = list(scan_result["findings"])
    if contract_result is not None:
        findings += list(contract_result.findings)
    findings.sort(key=lambda f: (f["line"], f["kind"]))
    return findings


def _status_line(scan_result, contract_result):
    count = len(scan_result["findings"])
    rate = scan_result["rate"]
    parts = [f"{count} fabrication(s) in {scan_result['lines']} lines = {rate:.1f} per 100 lines"]
    # A package that is not installed cannot be asked about, so every name reached through it
    # went unexamined. Saying which ones is the difference between "nothing was wrong here" and
    # "nothing here could be looked at" -- and only the reader can tell whether that matters.
    unchecked = scan_result.get("unchecked_imports") or []
    if unchecked:
        listed = ", ".join(unchecked[:4]) + ("..." if len(unchecked) > 4 else "")
        parts.append(f"NOT CHECKED: {listed} — not installed in the interpreter used, so "
                     f"names from {'them' if len(unchecked) > 1 else 'it'} were not examined")
    if contract_result is None:
        return parts
    if contract_result.status == "VIOLATED":
        parts.append(f"{len(contract_result.findings)} of {contract_result.examples} stated "
                     f"example(s) did not hold")
    elif contract_result.status == "OK":
        parts.append(f"all {contract_result.examples} stated example(s) held")
    elif contract_result.status == "NO_CONTRACT":
        parts.append(NO_CONTRACT_NOTE)
    else:
        parts.append(f"contracts UNCHECKED -- {contract_result.error}")
    return parts


# ------------------------------------------------------------------------------------- text
def render_text(path, scan_result, contract_result=None, colour=True):
    """What prints in a terminal. Compact by design: findings, not a wall of source."""
    red = "\033[31m" if colour else ""
    green = "\033[32m" if colour else ""
    dim = "\033[2m" if colour else ""
    off = "\033[0m" if colour else ""

    findings = _combine(scan_result, contract_result)
    out = [f"  {path}"]
    for line in _status_line(scan_result, contract_result):
        out.append(f"    {line}")
    if not findings:
        out.append(f"    {green}{CLEAN_NOTE}{off}")
        return "\n".join(out)
    out.append("")
    for finding in findings:
        out.append(f"    {red}line {finding['line']:>4}  {finding['kind']:<9}{off} "
                   f"{finding['detail']}")
    actions = sorted({FabricationClass.ACTION[f["kind"]]
                      for f in findings if f["kind"] in FabricationClass.ACTION})
    if actions:
        out.append("")
        for action in actions:
            out.append(f"    {dim}{action}{off}")
    return "\n".join(out)


# --------------------------------------------------------------------------------- markdown
def render_markdown(path, source, scan_result, contract_result=None):
    """The whole file, every line marked, details keyed by number.

    Marks sit in a fixed-width column ahead of the code so the source stays readable as source,
    and every flagged line carries a `#n` that matches a numbered note underneath. A reader --
    person or agent -- can go from a mark to its explanation without searching.
    """
    findings = _combine(scan_result, contract_result)
    by_line = {}
    for index, finding in enumerate(findings, 1):
        by_line.setdefault(finding["line"], []).append((index, finding))

    name = os.path.basename(path)
    out = [f"# hedgemony report: {name}", ""]
    for line in _status_line(scan_result, contract_result):
        out.append(f"- {line}")
    if not findings:
        out.append(f"- {CLEAN_NOTE}")
    out += ["", "`+` the line is clean · `!` something on this line does not exist "
                "or does not hold", "", "```"]

    lines = source.splitlines() or [""]
    width = len(str(len(lines)))
    for number, text in enumerate(lines, 1):
        hits = by_line.get(number)
        mark = "!" if hits else "+"
        tag = ("  " + " ".join(f"#{i}" for i, _ in hits)) if hits else ""
        out.append(f"{mark} {number:>{width}} | {text}{tag}")
    out.append("```")

    if findings:
        out += ["", "## findings", ""]
        for index, finding in enumerate(findings, 1):
            action = FabricationClass.ACTION.get(finding["kind"], "check this line")
            out.append(f"**#{index}** line {finding['line']} · `{finding['kind']}` — "
                       f"{finding['detail']}  \n  {action}")
            out.append("")
    out += ["---", "",
            "Every finding above is decided by the interpreter or a package registry, "
            "never by a language model.", ""]
    return "\n".join(out)


# ------------------------------------------------------------------------------------- html
# ONE STYLESHEET FOR EVERY PAGE THIS TOOL WRITES. A file report and a ranking are different
# views of the same measurement, so they use the same ground, the same type, the same two
# colours and the same rules. Anyone who has read one page can read the other without learning
# a second visual language.
_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; background:#000; color:#d0d0d0;
       font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
.wrap { max-width:1100px; margin:0 auto; padding:32px 20px 64px; }
h1 { font-size:15px; font-weight:600; letter-spacing:.12em; text-transform:uppercase;
     color:#fff; margin:0 0 4px; }
.sub { color:#6a6a6a; margin:0 0 24px; font-size:12px; }
.stat { border:1px solid #1e1e1e; padding:12px 14px; margin:0 0 8px; background:#060606; }
.stat b { color:#fff; font-weight:600; }
.clean { color:#3fb950; }
.bad { color:#f85149; }
.code { border:1px solid #1e1e1e; background:#060606; margin:24px 0 0;
        overflow-x:auto; padding:14px 0; }
table { border-collapse:collapse; width:100%; }
td { padding:0 8px; white-space:pre; vertical-align:top; }
td.n { color:#3a3a3a; text-align:right; user-select:none; width:1%;
       border-right:1px solid #1a1a1a; }
tr.ok td.t { color:#3fb950; }
tr.hit td.t { color:#f85149; }
tr.hit td.n { color:#f85149; }
td.r { color:#8b5cf6; width:1%; white-space:nowrap; }
h2 { font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:#8a8a8a;
     margin:32px 0 10px; }
.f { border-left:2px solid #f85149; padding:8px 0 8px 12px; margin:0 0 10px; }
.f .k { color:#f85149; }
.f .a { color:#6a6a6a; }
.foot { color:#4a4a4a; margin-top:36px; font-size:11px; border-top:1px solid #1a1a1a;
        padding-top:14px; }
.board { border:1px solid #1e1e1e; background:#060606; margin:24px 0 0; overflow-x:auto; }
.board table { width:100%; }
.board th { text-align:left; color:#6a6a6a; font-weight:400; font-size:11px;
            letter-spacing:.1em; text-transform:uppercase; padding:12px 14px;
            border-bottom:1px solid #1a1a1a; white-space:nowrap; }
.board td { padding:11px 14px; white-space:nowrap; border-bottom:1px solid #101010; }
.board tr:last-child td { border-bottom:0; }
.board td.lab { color:#fff; }
.board td.num { text-align:right; color:#8a8a8a; }
.board td.rate { text-align:right; font-weight:600; }
.board td.pos { color:#3a3a3a; width:1%; }
.board .r0 { color:#3fb950; }
.board .r1 { color:#d29922; }
.board .r2 { color:#f85149; }
.bar { display:inline-block; height:3px; background:currentColor; vertical-align:middle;
       margin-left:10px; min-width:1px; }
.note { color:#6a6a6a; margin:18px 0 0; font-size:12px; line-height:1.6; }
@media (max-width:640px){ .wrap{padding:20px 10px 40px} .board td,.board th{padding:9px 8px} }
"""


def render_html(path, source, scan_result, contract_result=None):
    """One self-contained page. Black ground, the code coloured green or red, nothing loaded."""
    findings = _combine(scan_result, contract_result)
    by_line = {}
    for index, finding in enumerate(findings, 1):
        by_line.setdefault(finding["line"], []).append((index, finding))

    name = html.escape(os.path.basename(path))
    rows = []
    for number, text in enumerate((source.splitlines() or [""]), 1):
        hits = by_line.get(number)
        css = "hit" if hits else "ok"
        refs = " ".join(f"#{i}" for i, _ in hits) if hits else ""
        rows.append(f'<tr class="{css}"><td class="n">{number}</td>'
                    f'<td class="t">{html.escape(text) or "&nbsp;"}</td>'
                    f'<td class="r">{refs}</td></tr>')

    stats = "".join(f'<div class="stat">{html.escape(s)}</div>'
                    for s in _status_line(scan_result, contract_result))
    if not findings:
        stats += f'<div class="stat clean">{html.escape(CLEAN_NOTE)}</div>'

    detail = ""
    if findings:
        items = []
        for index, finding in enumerate(findings, 1):
            action = FabricationClass.ACTION.get(finding["kind"], "check this line")
            items.append(
                f'<div class="f"><span class="k">#{index} · line {finding["line"]} · '
                f'{html.escape(finding["kind"])}</span> — {html.escape(finding["detail"])}'
                f'<br><span class="a">{html.escape(action)}</span></div>')
        detail = "<h2>findings</h2>" + "".join(items)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>hedgemony · {name}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>hedgemony</h1>
<p class="sub">{name}</p>
{stats}
{detail}
<div class="code"><table>{''.join(rows)}</table></div>
<p class="foot">Every finding is decided by the interpreter or a package registry, never by a
language model. A clean result means no fabricated name was found; it is not a proof of
correctness.</p>
</div></body></html>"""


# ------------------------------------------------------------------------------------ board
# The caveat travels with every rendering of the ranking. A rate rewards a source that wrote
# less, and a reader who sees only the ordering will not know that. It is printed next to the
# numbers rather than kept in the documentation, because the person misreading the table is
# looking at the table.
BOARD_CAVEAT = ("a rate measures defects, not capability -- a source can score well by "
                "attempting less, so read the line counts alongside it")
BOARD_SUBTITLE = ("defects per 100 lines: invented names plus stated examples that did not "
                  "hold, decided by the interpreter -- never by a language model")


def _band(index, total):
    """Best third green, middle amber, worst third red. Position, not an absolute threshold."""
    if total < 2:
        return "r0"
    return "r0" if index < total / 3 else ("r1" if index < 2 * total / 3 else "r2")


def render_board_text(sources, colour=True):
    green, amber, red = ("\033[32m", "\033[33m", "\033[31m") if colour else ("", "", "")
    dim = "\033[2m" if colour else ""
    off = "\033[0m" if colour else ""
    tone = {"r0": green, "r1": amber, "r2": red}

    out = ["", "  RANKED BY DEFECTS PER 100 LINES  (lower is better)", ""]
    out.append(f"  {'':<3}{'source':<22}{'per 100':>9}{'names':>7}{'contracts':>14}"
               f"{'lines':>8}{'files':>7}")
    total = len(sources)
    for index, source in enumerate(sources):
        colourise = tone[_band(index, total)]
        contracts = (f"{source.contracts_broken} broken" if source.contracts_broken
                     else f"{source.examples} held" if source.examples else "none stated")
        out.append(f"  {index + 1:<3}{source.label[:21]:<22}"
                   f"{colourise}{source.defect_rate:>9.1f}{off}"
                   f"{source.fabrications:>7}{contracts:>14}"
                   f"{source.lines:>8}{source.files:>7}")
        for detail, count in source.top[:2]:
            out.append(f"      {dim}{count}x  {detail[:64]}{off}")
    out += ["", f"  {dim}{BOARD_CAVEAT}{off}", ""]
    return "\n".join(out)


def render_board_markdown(sources):
    out = ["# hedgemony leaderboard", "", f"_{BOARD_SUBTITLE}_", "",
           "| # | source | defects per 100 | invented names | contracts | lines | files |",
           "|---|---|---:|---:|---|---:|---:|"]
    for index, source in enumerate(sources, 1):
        contracts = (f"{source.contracts_broken} broken" if source.contracts_broken
                     else f"{source.examples} held" if source.examples else "none stated")
        out.append(f"| {index} | `{source.label}` | **{source.defect_rate:.1f}** | "
                   f"{source.fabrications} | {contracts} | {source.lines} | {source.files} |")
    out += ["", "## most frequent findings", ""]
    for source in sources:
        if source.top:
            out.append(f"**{source.label}**")
            for detail, count in source.top:
                out.append(f"- {count}x — {detail}")
            out.append("")
    out += ["---", "", BOARD_CAVEAT, ""]
    return "\n".join(out)


def render_board_html(sources):
    """The ranking, in the same visual language as a file report."""
    worst = max((s.defect_rate for s in sources), default=0.0) or 1.0
    total = len(sources)
    rows = []
    for index, source in enumerate(sources):
        band = _band(index, total)
        contracts = (f"{source.contracts_broken} broken" if source.contracts_broken
                     else f"{source.examples} held" if source.examples else "none stated")
        width = max(1, round(120 * source.defect_rate / worst))
        rows.append(
            f'<tr><td class="pos">{index + 1}</td>'
            f'<td class="lab">{html.escape(source.label)}</td>'
            f'<td class="rate {band}">{source.defect_rate:.1f}'
            f'<span class="bar" style="width:{width}px"></span></td>'
            f'<td class="num">{source.fabrications}</td>'
            f'<td class="num">{html.escape(contracts)}</td>'
            f'<td class="num">{source.lines}</td>'
            f'<td class="num">{source.files}</td></tr>')

    detail = ""
    items = []
    for source in sources:
        if source.top:
            lines = "".join(f'<div class="a">{count}x — {html.escape(text)}</div>'
                            for text, count in source.top)
            items.append(f'<div class="f"><span class="k">{html.escape(source.label)}</span>'
                         f'{lines}</div>')
    if items:
        detail = "<h2>most frequent findings</h2>" + "".join(items)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>hedgemony · leaderboard</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>hedgemony</h1>
<p class="sub">leaderboard · lower is better</p>
<div class="stat">{html.escape(BOARD_SUBTITLE)}</div>
<div class="board"><table>
<tr><th></th><th>source</th><th>defects per 100</th><th>invented names</th><th>contracts</th>
<th>lines</th><th>files</th></tr>
{''.join(rows)}
</table></div>
<p class="note">{html.escape(BOARD_CAVEAT)}</p>
{detail}
<p class="foot">Every finding is decided by the interpreter or a package registry, never by a
language model. A clean result means no fabricated name was found; it is not a proof of
correctness.</p>
</div></body></html>"""


def write_report(source_path, source, scan_result, contract_result=None, fmt="md"):
    """Write the report to its one fixed location and return that path."""
    target = report_path(source_path, "html" if fmt == "html" else "md")
    body = (render_html(source_path, source, scan_result, contract_result) if fmt == "html"
            else render_markdown(source_path, source, scan_result, contract_result))
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(body)
    return target
