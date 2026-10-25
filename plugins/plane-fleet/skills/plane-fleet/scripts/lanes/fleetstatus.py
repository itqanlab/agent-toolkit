#!/usr/bin/env python3
"""fleetstatus — the PM's whole view of the fleet in one call.

Measured 2026-10-25 on one project: the PM spent about 2,000 calls a month reading the usage
meter, looping over slot ports, and polling PRs and CI one at a time, each call carrying a
median 300k+ tokens of context. `run-lane.sh status` answers all of it at once: budget, slots
and who holds them, lanes running and just ended, open PRs with their required checks, labels
and mergeability, trunk CI, and worktrees left with no open PR. The board itself stays a Plane
MCP read.

Standard library only. Python 3.9.
"""
import datetime, glob, json, os, re, subprocess, time

RECENT_S = 6 * 3600


def sh(args, cwd=None, timeout=60):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    if r.returncode:
        return None, (r.stderr.strip().splitlines() or ["exit %d" % r.returncode])[-1]
    return r.stdout, None


def ago(t, now=None):
    if not t:
        return "?"
    s = max(0, (now or time.time()) - t)
    return f"{s / 60:.0f}m" if s < 5400 else f"{s / 3600:.1f}h"


def epoch(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------- checks
def check_state(c):
    """One rollup entry -> pass | fail | running | skipped."""
    if c.get("__typename") == "StatusContext":
        st = (c.get("state") or "").upper()
        return {"SUCCESS": "pass", "FAILURE": "fail", "ERROR": "fail"}.get(st, "running")
    if (c.get("status") or "").upper() != "COMPLETED":
        return "running"
    con = (c.get("conclusion") or "").upper()
    if con in ("SUCCESS", "NEUTRAL"):
        return "pass"
    if con == "SKIPPED":
        return "skipped"
    return "fail"


def summarize_checks(rollup, required=()):
    """(text, required_state). Latest run per check name wins. required_state: green, red,
    running, missing (a required job has not run) or n/a (no required jobs configured)."""
    latest = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        t = c.get("startedAt") or c.get("completedAt") or ""
        if name not in latest or t >= latest[name][0]:
            latest[name] = (t, check_state(c))
    counts = {}
    for _, st in latest.values():
        counts[st] = counts.get(st, 0) + 1
    fails = sorted(n for n, (_, st) in latest.items() if st == "fail")
    req = None
    if required:
        sts = [latest.get(j, (None, "missing"))[1] for j in required]
        req = "red" if "fail" in sts else "running" if "running" in sts else "missing" if "missing" in sts else "green"
    text = " ".join(f"{counts[k]} {k}" for k in ("pass", "running", "fail", "skipped") if counts.get(k)) or "no checks"
    if fails:
        text += " (" + ", ".join(fails[:3]) + (" …" if len(fails) > 3 else "") + ")"
    return text, req or "n/a"


# ---------------------------------------------------------------- slots
def listeners():
    """{port: pid} for every TCP listener, from one lsof call."""
    out, _ = sh(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pn"], timeout=20)
    res, pid = {}, None
    for line in (out or "").splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            m = re.search(r":(\d+)$", line)
            if m:
                res.setdefault(int(m.group(1)), pid)
    return res


def cwd_of(pid):
    out, _ = sh(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], timeout=10)
    for line in (out or "").splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def slots_view(cfg, repo):
    slots = (cfg.get("fleet") or {}).get("slots") or {}
    ports = listeners()
    parts = []
    for name, s in slots.items():
        if not isinstance(s, dict) or name.startswith("$"):
            continue
        busy = [(k, s[k], ports[s[k]]) for k in ("api", "client") if isinstance(s.get(k), int) and s[k] in ports]
        if name == "shared":
            parts.append(f"shared {'up' if busy else 'down'} (owner's, never assigned)")
            continue
        if not busy:
            parts.append(f"{name} free")
            continue
        where = cwd_of(busy[0][2]) or "?"
        if repo and where.startswith(repo):
            where = where[len(repo):].lstrip("/") or "."
        parts.append(f"{name} busy ({'+'.join(k for k, _, _ in busy)} · {where})")
    return parts


# ---------------------------------------------------------------- lanes
def lanes_view(state_home, repo, now=None):
    now = now or time.time()
    running, ended = [], []
    for p in sorted(glob.glob(os.path.join(state_home, "lanes", "*.json"))):
        try:
            with open(p) as f:
                l = json.load(f)
        except (OSError, ValueError):
            continue
        if repo and l.get("cwd") and not str(l["cwd"]).startswith(repo):
            continue
        start = epoch(l.get("startedAt"))
        who = f"{l.get('executor')}:{l.get('model')} {l.get('role')} {l.get('ticket')}"
        if l.get("status") == "running":
            alive = False
            try:
                os.kill(int(l.get("pid") or 0), 0)
                alive = bool(l.get("pid"))
            except (OSError, ValueError):
                pass
            running.append(f"{who} · {ago(start, now)}" + ("" if alive else " · PROCESS GONE (dead lane)"))
        else:
            end = epoch(l.get("finishedAt"))
            if end and now - end <= RECENT_S:
                ended.append(f"{who} · {l.get('status')} {ago(end, now)} ago")
    return running, ended


# ---------------------------------------------------------------- PRs, CI, worktrees
def prs_view(repo, cfg, ident_re):
    out, err = sh(["gh", "pr", "list", "--state", "open", "--limit", "100", "--json",
                   "number,title,headRefName,baseRefName,isDraft,labels,mergeable,statusCheckRollup,updatedAt"], cwd=repo)
    if err:
        return None, err
    required = (cfg.get("ci") or {}).get("required_jobs") or ()
    rows = []
    for p in json.loads(out):
        text, req = summarize_checks(p.get("statusCheckRollup"), required)
        tickets = sorted(set(ident_re.findall((p.get("headRefName") or "") + " " + (p.get("title") or ""))))
        labels = [l.get("name") for l in p.get("labels") or []]
        rows.append({"number": p["number"], "tickets": tickets, "branch": p.get("headRefName"), "base": p.get("baseRefName"),
                     "draft": p.get("isDraft"), "labels": labels, "mergeable": p.get("mergeable"), "checks": text,
                     "required": req, "updated": p.get("updatedAt")})
    return rows, None


def trunk_ci(repo, trunk):
    out, err = sh(["gh", "run", "list", "--branch", trunk, "--limit", "5", "--json",
                   "name,status,conclusion,createdAt,event"], cwd=repo)
    if err:
        return None, err
    return json.loads(out), None


def worktrees_view(repo, open_branches):
    out, _ = sh(["git", "-C", repo, "worktree", "list", "--porcelain"])
    trees, cur = [], {}
    for line in (out or "").splitlines() + [""]:
        if not line:
            if cur:
                trees.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "")
    extra = [t for t in trees[1:]]
    orphan = [t for t in extra if t.get("branch") not in open_branches]
    return extra, orphan


# ---------------------------------------------------------------- render
def collect(fleetctl, cwd):
    reg = fleetctl.load_registry(cwd)
    cfg = fleetctl.project_config(cwd)
    common = fleetctl.git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    repo = os.path.dirname(common.rstrip("/")) if common else (fleetctl.git(cwd, "rev-parse", "--show-toplevel") or cwd)
    ident = (cfg.get("plane") or {}).get("identifier")
    ident_re = re.compile(r"\b(" + (re.escape(ident) if ident else r"[A-Z][A-Z0-9]{1,9}") + r"-\d+)\b")
    trunk = (cfg.get("git") or {}).get("trunk") or "main"
    prs, pr_err = prs_view(repo, cfg, ident_re)
    runs, run_err = trunk_ci(repo, trunk)
    running, ended = lanes_view(fleetctl.STATE_HOME, repo)
    trees, orphan = worktrees_view(repo, {p["branch"] for p in prs or []})
    return {"project": reg.get("_project"), "repo": repo, "trunk": trunk, "budget": fleetctl.budget_line(reg),
            "slots": slots_view(cfg, repo), "lanes_running": running, "lanes_ended": ended,
            "prs": prs, "prs_error": pr_err, "trunk_runs": runs, "trunk_error": run_err,
            "worktrees": len(trees), "orphan_worktrees": [t.get("path", "")[len(repo):].lstrip("/") for t in orphan]}


def render(s):
    t = datetime.datetime.now().strftime("%H:%M")
    L = [f"Fleet status · {s['project']} · {t}", f"budget: {s['budget']}", "slots: " + (" · ".join(s["slots"]) or "none configured")]
    L.append(f"lanes running ({len(s['lanes_running'])}): " + (" | ".join(s["lanes_running"]) or "none"))
    if s["lanes_ended"]:
        L.append("lanes ended (6h): " + " | ".join(s["lanes_ended"]))
    if s["prs_error"]:
        L.append(f"open PRs: gh failed: {s['prs_error']}")
    else:
        prs = s["prs"]
        ready = [p for p in prs if p["required"] == "green" and "qa-approved" in p["labels"]]
        L.append(f"open PRs ({len(prs)}; approved with required checks green: {len(ready)}):")
        for p in sorted(prs, key=lambda p: p["number"]):
            if p["draft"] and p["required"] == "missing":
                p["required"] = "on group"   # ticket PRs stay drafts; the required jobs run on the group PR
            flags = ["draft" if p["draft"] else "ready"]
            if p["mergeable"] and p["mergeable"] != "MERGEABLE":
                flags.append(p["mergeable"].lower())
            if p["base"] != s["trunk"]:
                flags.append(f"base {p['base']}")
            L.append(f"  #{p['number']} {','.join(p['tickets']) or p['branch'][:30]:<12} required {p['required']:<9} "
                     f"{p['checks'][:60]:<62}{' '.join(flags)}" + (f"  [{', '.join(p['labels'])}]" if p["labels"] else ""))
    if s["trunk_error"]:
        L.append(f"trunk {s['trunk']}: gh failed: {s['trunk_error']}")
    elif s["trunk_runs"]:
        L.append(f"trunk {s['trunk']}: " + " · ".join(
            f"{r['name']} {(r.get('conclusion') or r.get('status') or '?').lower()} {ago(epoch(r.get('createdAt')))} ago"
            for r in s["trunk_runs"][:4]))
    L.append(f"worktrees: {s['worktrees']}" + (f", {len(s['orphan_worktrees'])} with no open PR: "
                                                 + ", ".join(s["orphan_worktrees"][:6]) if s["orphan_worktrees"] else ""))
    return "\n".join(L)


def run(fleetctl, args):
    s = collect(fleetctl, args.cwd or os.getcwd())
    print(json.dumps(s, indent=2) if args.json else render(s))
    return 0


# ---------------------------------------------------------------- selftest
def selftest(check):
    roll = [{"__typename": "CheckRun", "name": "unit", "status": "COMPLETED", "conclusion": "FAILURE", "startedAt": "2026-10-25T08:00:00Z"},
            {"__typename": "CheckRun", "name": "unit", "status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": "2026-10-25T09:00:00Z"},
            {"__typename": "CheckRun", "name": "e2e", "status": "IN_PROGRESS", "conclusion": "", "startedAt": "2026-10-25T09:00:00Z"},
            {"__typename": "CheckRun", "name": "lint", "status": "COMPLETED", "conclusion": "SKIPPED"},
            {"__typename": "StatusContext", "context": "deploy", "state": "FAILURE"}]
    text, req = summarize_checks(roll, ["unit", "e2e"])
    check("status: a re-run's latest result wins", text.startswith("1 pass 1 running 1 fail 1 skipped"), True)
    check("status: required still running", req, "running")
    check("status: a required job that never ran", summarize_checks(roll, ["unit", "build"])[1], "missing")
    check("status: required all green", summarize_checks(roll[:2], ["unit"])[1], "green")
