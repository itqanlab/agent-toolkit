#!/usr/bin/env python3
"""fleetfindings: the findings of a review transcript, without the transcript.

A `codex review` or `codex exec` run writes everything it read into its output: file dumps,
diffs, test logs. The findings are a few lines at the end. 2026-11-01, one project: the PM read
a whole 283 KB review transcript to get two findings, and every later PM call carried it.

  fleet findings <file> [--titles]

Prints one count line, then the final findings block, deduplicated: the last
"Full review comments:" / "Review comment(s):" section, else the P1/P2/P3 items in the final
message, else the final message itself, cut short. `--titles` drops each finding's body.

Exit codes: 0 no P1 or P2 open, 3 a P1 or P2 is listed, 4 the review did not finish (an error
or a usage limit, so no verdict), 2 the file can't be read.
Standard library only. Python 3.9.
"""
import os, re, sys

HEAD_RE = re.compile(r"^\s*(full review comments|review comments?)\s*:\s*$", re.I)
ITEM_RE = re.compile(r"^\s*(?:[-*]\s*|\d+[.)]\s*)?(?:\*\*)?\[?(P[0-3])\]?(?:\*\*)?[:.]?\s+(.+)$")
CODEX_RE = re.compile(r"^codex\s*$")
END_RE = re.compile(r"^tokens used\b", re.I)
UNFINISHED_RE = re.compile(r"^(ERROR\b|Review was interrupted)|usage limit|rate limit", re.I)
BODY_MAX = 800
FALLBACK_LINES = 40


def final_message(lines):
    """Lines after the last bare 'codex' marker (codex prints the agent's turn under it),
    up to 'tokens used'. Without a marker, the whole file."""
    start = 0
    for i, l in enumerate(lines):
        if CODEX_RE.match(l):
            start = i + 1
    out = []
    for l in lines[start:]:
        if END_RE.match(l):
            break
        out.append(l)
    return out, start > 0


def parse_items(lines):
    """[(priority, title, body)] from '- [P1] title — path:lines' items and their indented body."""
    items, cur = [], None
    for l in lines:
        m = ITEM_RE.match(l)
        if m and (l.lstrip().startswith(("-", "*", "[", "P")) or l.lstrip()[:1].isdigit()):
            cur = [m.group(1).upper(), m.group(2).strip(), []]
            items.append(cur)
            continue
        if cur is None:
            continue
        if not l.strip():
            cur[2].append("")
            continue
        if l.startswith((" ", "\t")):
            cur[2].append(l.strip())
        else:
            cur = None
    return [(p, t, " ".join(x for x in b if x).strip()) for p, t, b in items]


def dedupe(items):
    seen, out = set(), []
    for p, t, b in items:
        k = (p, t)
        if k in seen:
            continue
        seen.add(k)
        out.append((p, t, b))
    return out


def extract(text):
    """-> (summary lines, [(priority, title, body)], raw item count, how found)."""
    lines = text.splitlines()
    heads = [i for i, l in enumerate(lines) if HEAD_RE.match(l)]
    if heads:
        h = heads[-1]
        block = lines[h + 1:]
        block = block[:next((i for i, l in enumerate(block) if END_RE.match(l)), len(block))]
        # the summary is the paragraph just above the heading
        j = h - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        k = j
        while k >= 0 and lines[k].strip() and not CODEX_RE.match(lines[k]) \
                and not lines[k].startswith((" ", "\t")) and not ITEM_RE.match(lines[k]):
            k -= 1
        summary = [l for l in lines[k + 1:j + 1] if l.strip()][-3:]
        raw = parse_items(block)
        return summary, dedupe(raw), len(raw), "review block"
    msg, marked = final_message(lines)
    raw = parse_items(msg)
    if raw:
        return [], dedupe(raw), len(raw), "final message"
    if not marked:
        raw = parse_items(lines)
        if raw:
            return [], dedupe(raw), len(raw), "whole file"
    tail = list(dict.fromkeys(l for l in msg if l.strip()))   # codex prints its last message twice
    if any(UNFINISHED_RE.search(l) for l in tail):
        return tail[-FALLBACK_LINES:], [], 0, "the review did not finish"
    return tail[-FALLBACK_LINES:], [], 0, "final message, no P1-P3 items"


def render(path, text, titles=False):
    summary, items, raw, how = extract(text)
    n = {p: sum(1 for x in items if x[0] == p) for p in ("P0", "P1", "P2", "P3")}
    p1 = n["P0"] + n["P1"]
    count = (f"findings: {p1} P1, {n['P2']} P2, {n['P3']} P3"
             + (f" ({len(items)} after removing {raw - len(items)} repeats)" if raw > len(items) else "")
             + f" · {how} · {os.path.basename(path)} {len(text) // 1024} KB")
    L = [count]
    L += summary
    for p, t, b in items:
        L.append(f"- [{p}] {t}")
        if b and not titles:
            L.append("  " + (b if len(b) <= BODY_MAX else b[:BODY_MAX].rstrip() + " …"))
    return "\n".join(L), (3 if (p1 or n["P2"]) else 4 if how == "the review did not finish" else 0)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n", 2)[2].split("Exit codes")[0].rstrip())
        return 0 if argv else 2
    if argv[0] == "--selftest":
        return selftest()
    titles = "--titles" in argv
    files = [a for a in argv if not a.startswith("--")]
    if len(files) != 1:
        print("usage: fleet findings <file> [--titles]", file=sys.stderr)
        return 2
    try:
        with open(files[0], errors="replace") as f:
            text = f.read()
    except OSError as e:
        print(f"fleet findings: cannot read {files[0]}: {e}", file=sys.stderr)
        return 2
    out, code = render(files[0], text, titles)
    print(out)
    return code


# ---------------------------------------------------------------- selftest
SAMPLE = """exec
/bin/zsh -lc 'sed -n 1,400p big.ts'
- [P1] not a finding, a line inside a file the reviewer read
codex
The flow is right, but one path leaves stale data.

Review comment:

- [P2] Route stale failures through the refresh handler — /repo/a.ts:202-208
  When the plan changes first, the drawer stays open.
  Detect it and reload.
The flow is right, but one path leaves stale data.

Review comment:

- [P2] Route stale failures through the refresh handler — /repo/a.ts:202-208
  When the plan changes first, the drawer stays open.
  Detect it and reload.
- [P1] Book the refund once — /repo/b.ts:10-12
  Two clicks book it twice.
"""
EXEC = """user
review it
codex
Looked at the diff.
1. **P1** Missing audit row on the cancel path — x.ts:4
2. P3: rename the helper
tokens used
12,345
"""
BROKEN = """codex
Review was interrupted. Please re-run /review and wait for it to complete.
ERROR: You've hit your usage limit.
"""
CLEAN = """codex
I did not find any discrete, actionable bugs in this diff.
"""


def selftest(check=None):
    fails = []

    def chk(name, got, want):
        if check:
            return check(name, got, want)
        ok = got == want
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": got {got!r}, want {want!r}"))
        if not ok:
            fails.append(name)
    s, items, raw, how = extract(SAMPLE)
    chk("findings: last block only", [(p, t.split(" — ")[0]) for p, t, _ in items],
        [("P2", "Route stale failures through the refresh handler"), ("P1", "Book the refund once")])
    chk("findings: body kept", items[0][2], "When the plan changes first, the drawer stays open. Detect it and reload.")
    chk("findings: summary line", s, ["The flow is right, but one path leaves stale data."])
    out, code = render("r.md", SAMPLE + SAMPLE)
    chk("findings: count line", out.splitlines()[0].startswith("findings: 1 P1, 1 P2, 0 P3"), True)
    chk("findings: exit 3 on an open P1/P2", code, 3)
    _, items, _, how = extract(EXEC)
    chk("findings: codex exec list", [(p, how) for p, _, _ in items], [("P1", "final message"), ("P3", "final message")])
    out, code = render("c.md", CLEAN)
    chk("findings: a clean review", (code, "0 P1, 0 P2" in out, "did not find" in out), (0, True, True))
    chk("findings: an unfinished review is not clean", render("b.md", BROKEN)[1], 4)
    out, _ = render("r.md", SAMPLE, titles=True)
    chk("findings: --titles drops bodies", "drawer stays open" in out, False)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
