#!/usr/bin/env python3
"""fleetstatus — the PM's whole view of the fleet in one call.

Measured 2026-10-25 on one project: the PM spent about 2,000 calls a month reading the usage
meter, looping over slot ports, and polling PRs and CI one at a time, each call carrying a
median 300k+ tokens of context. `fleet status` answers all of it at once: budget, slots
and who holds them, lanes running and just ended, open PRs with their required checks, labels
and mergeability, trunk CI, and worktrees left with no open PR. The board itself stays a Plane
MCP read.

Held work: the PM records a Todo ticket it skips for its blockers with `fleet held set`, from the
relations it already read at pick time. Status then needs no Plane call to say when that ticket
could start now, stacked on its blockers' pushed branches.

Standard library only. Python 3.9.
"""
import datetime, glob, json, os, re, subprocess, time

RECENT_S = 6 * 3600
HELD_SEEN_KEEP = 5000      # sightings kept in the held-work log


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
    """(text, required_state). Latest run per check name wins, except that a skipped run never
    hides a real one (a skipped duplicate can sit under the same name while the real run goes).
    required_state: green, red, running, missing (a required job has not run) or n/a (no
    required jobs configured)."""
    latest = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        t = c.get("startedAt") or c.get("completedAt") or ""
        st = check_state(c)
        cur = latest.get(name)
        if cur is None or ((st != "skipped", t) >= (cur[1] != "skipped", cur[0])):
            latest[name] = (t, st)
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


# ---------------------------------------------------------------- held work
# Measured on one project: the PM held a ticket about 3 hours for a blocker that sat in an open
# group PR. 16 tickets waited behind it, and the machine had room for 4 heavy jobs while 1 or 2
# ran. pick.md already said to start it stacked. Nothing checked.
def held_paths(state_home, project):
    d = os.path.join(state_home, "held")
    return os.path.join(d, f"{project}.json"), os.path.join(d, f"{project}-seen.jsonl")


def load_held(path):
    """{ticket: {"blocked_by": [...], "since": iso}} or {} when nothing is recorded."""
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    t = d.get("tickets") if isinstance(d, dict) else None
    return t if isinstance(t, dict) else {}


def save_held(path, tickets):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"tickets": tickets}, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def seq(t):
    m = re.search(r"-(\d+)$", t or "")
    return (t.rsplit("-", 1)[0], int(m.group(1))) if m else (t or "", 0)


def free_slot_count(slots):
    return sum(1 for p in slots if p.endswith(" free") and not p.startswith("shared"))


def held_work(held, prs, free_slots, gate, running=()):
    """The held tickets that could start now, stacked on their blockers' pushed branches.

    A ticket qualifies when every blocker has an open PR (draft, approved, or named in a group
    PR), at least one slot is free and the machine admits a heavy spawn (ok, or tight with room).
    A ticket that already has its own PR or a running lane is not held any more."""
    import fleetres
    if not held or free_slots < 1 or not fleetres.admit(gate, True):
        return []
    by = {}
    for p in prs or []:
        for t in p.get("tickets") or []:
            by.setdefault(t, []).append(p)
    busy = " ".join(running)
    out = []
    for t in sorted(held, key=seq):
        blockers = [b for b in (held[t].get("blocked_by") or []) if b != t]
        if not blockers or t in by or re.search(r"(^|[^A-Za-z0-9-])" + re.escape(t) + r"([^0-9]|$)", busy):
            continue
        found = []
        for b in blockers:
            ps = by.get(b) or []
            own = [p for p in ps if not str(p.get("branch") or "").startswith("release/")]
            group = [p for p in ps if str(p.get("branch") or "").startswith("release/")]
            pick = (own or group or [None])[0]
            if not pick:
                break
            found.append({"ticket": b, "pr": pick["number"], "branch": pick["branch"],
                          "group": group[0]["number"] if group and own else None,
                          "approved": "qa-approved" in (pick.get("labels") or [])})
        else:
            branches = list(dict.fromkeys(f["branch"] for f in found))
            out.append({"ticket": t, "blockers": found, "stack_on": branches[0], "merge_in": branches[1:],
                        "since": held[t].get("since")})
    return out


def held_lines(items, free_slots):
    if not items:
        return []
    L = [f"held work ({len(items)}; {free_slots} slot(s) free, machine has room). Start it stacked now, "
         "or log why not (pick.md):"]
    for h in items:
        bl = ", ".join(f"{b['ticket']} #{b['pr']}" + (" approved" if b["approved"] else "")
                       + (f" in group #{b['group']}" if b["group"] else "") for b in h["blockers"])
        tail = f" then merge in {', '.join(h['merge_in'])}" if h["merge_in"] else ""
        L.append(f"  {h['ticket']} held by {bl} · stack on {h['stack_on']}{tail}"
                 + (f" · held {ago(epoch(h['since']))}" if h.get("since") else ""))
    return L


def record_seen(path, items, free_slots, now=None):
    """One line per held ticket per status call. `fleet retro` turns these into held hours."""
    if not items:
        return
    ts = datetime.datetime.fromtimestamp(now or time.time(), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            for h in items:
                f.write(json.dumps({"ts": ts, "ticket": h["ticket"], "blocked_by": [b["ticket"] for b in h["blockers"]],
                                    "free_slots": free_slots}) + "\n")
        with open(path) as f:
            lines = f.readlines()
        if len(lines) > HELD_SEEN_KEEP:
            with open(path, "w") as f:
                f.writelines(lines[-HELD_SEEN_KEEP:])
    except OSError:
        pass


def prune_held(held, prs):
    """Drop held tickets that now have a PR of their own: they were started."""
    started = {t for p in prs or [] if not str(p.get("branch") or "").startswith("release/") for t in p.get("tickets") or []}
    return {t: v for t, v in held.items() if t not in started}


def held_cmd(fleetctl, args):
    """fleet held set T --blocked-by A,B | clear T [T ...] | list"""
    cwd = args.cwd or os.getcwd()
    project = fleetctl.load_registry(cwd).get("_project") or "default"
    path, _ = held_paths(fleetctl.STATE_HOME, project)
    held = load_held(path)
    if args.action == "set":
        blockers = [b.strip() for b in (args.blocked_by or "").split(",") if b.strip()]
        if len(args.tickets) != 1 or not blockers:
            raise SystemExit("fleet held set: one ticket and --blocked-by A[,B] are required")
        t = args.tickets[0]
        old = held.get(t) or {}
        held[t] = {"blocked_by": blockers, "since": old.get("since") or
                   datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        save_held(path, held)
        print(f"held: {t} blocked by {', '.join(blockers)}")
    elif args.action == "clear":
        gone = [t for t in args.tickets if held.pop(t, None) is not None]
        save_held(path, held)
        print("held: cleared " + (", ".join(gone) or "nothing"))
    else:
        if args.json:
            print(json.dumps(held, indent=2, sort_keys=True))
        else:
            for t in sorted(held, key=seq):
                print(f"{t} blocked by {', '.join(held[t].get('blocked_by') or [])} since {held[t].get('since')}")
            if not held:
                print("held: nothing recorded")
    return 0


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
    import fleetres
    fcfg, fpaths, wdirs = fleetres.context(cwd)
    sample = fleetres.attach_tool_caches(fleetres.probe(fpaths, top_n=8), fcfg)
    gate = fleetres.judge(sample, fcfg, wdirs)
    machine = {"summary": fleetres.summary_line(sample, gate), **gate}
    slots = slots_view(cfg, repo)
    held_path, seen_path = held_paths(fleetctl.STATE_HOME, reg.get("_project") or "default")
    held = load_held(held_path)
    if held and prs is not None:
        kept = prune_held(held, prs)
        if kept != held:
            try:
                save_held(held_path, kept)
            except OSError:
                pass
        held = kept
    free = free_slot_count(slots)
    held_items = held_work(held, prs, free, gate, running) if prs is not None else []
    record_seen(seen_path, held_items, free)
    return {"held_work": held_items, "held_recorded": len(held),
            "machine": machine, "project": reg.get("_project"), "repo": repo, "trunk": trunk, "budget": fleetctl.budget_line(reg),
            "slots": slots, "lanes_running": running, "lanes_ended": ended,
            "prs": prs, "prs_error": pr_err, "trunk_runs": runs, "trunk_error": run_err,
            "worktrees": len(trees), "orphan_worktrees": [t.get("path", "")[len(repo):].lstrip("/") for t in orphan]}


def render(s):
    t = datetime.datetime.now().strftime("%H:%M")
    m = s["machine"]
    L = [f"Fleet status · {s['project']} · {t}", f"machine: {m['summary']}"]
    L += [f"  {r}" for r in m["reasons"] if not r.startswith("tight")]
    L += [f"  hog pid {h['pid']} {h['name']} {h['mem_gb']} GB: {h.get('what', '?')}, fix: {h.get('fix', 'find its owner')}"
          for h in m["hogs"] if not h["fleet"] and h.get("safe")]
    L += [f"  warning: {w}" for w in m["warnings"]]
    L += [f"budget: {s['budget']}", "slots: " + (" · ".join(s["slots"]) or "none configured")]
    L += held_lines(s.get("held_work"), free_slot_count(s["slots"]))
    L.append(f"lanes running ({len(s['lanes_running'])}): " + (" | ".join(s["lanes_running"]) or "none"))
    if s["lanes_ended"]:
        L.append("lanes ended (6h): " + " | ".join(s["lanes_ended"]))
    if s["prs_error"]:
        L.append(f"open PRs: gh failed: {s['prs_error']}")
    else:
        prs = s["prs"]
        ready = [p for p in prs if p["required"] == "green" and "qa-approved" in p["labels"]]
        L.append(f"open PRs ({len(prs)}; approved with required checks green: {len(ready)}):")
        loud = [p for p in prs if ready_ticket_pr(p, s["trunk"])]
        if loud:
            # measured 2026-11-16, one project: ticket PRs out of draft used about 3,600 runner minutes in 18 days
            L.append(f"  WARNING {len(loud)} ticket PR(s) out of draft run the full CI on every push: "
                     + " ".join(f"gh pr ready --undo {p['number']};" for p in loud))
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
def ready_ticket_pr(p, trunk):
    """A ticket PR out of draft runs the full CI on every push. Only group and release PRs should."""
    return (not p.get("draft") and bool(p.get("tickets")) and not str(p.get("branch") or "").startswith("release/")
            and p.get("base") == trunk)


def selftest(check):
    tp = {"draft": False, "tickets": ["P-1"], "branch": "feat/P-1-x", "base": "develop"}
    check("status: a ticket PR out of draft is flagged", ready_ticket_pr(tp, "develop"), True)
    check("status: a group PR is not", ready_ticket_pr({**tp, "branch": "release/group-1"}, "develop"), False)
    check("status: a draft is not", ready_ticket_pr({**tp, "draft": True}, "develop"), False)
    roll = [{"__typename": "CheckRun", "name": "unit", "status": "COMPLETED", "conclusion": "FAILURE", "startedAt": "2026-10-25T08:00:00Z"},
            {"__typename": "CheckRun", "name": "unit", "status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": "2026-10-25T09:00:00Z"},
            {"__typename": "CheckRun", "name": "e2e", "status": "IN_PROGRESS", "conclusion": "", "startedAt": "2026-10-25T09:00:00Z"},
            {"__typename": "CheckRun", "name": "lint", "status": "COMPLETED", "conclusion": "SKIPPED"},
            {"__typename": "StatusContext", "context": "deploy", "state": "FAILURE"}]
    text, req = summarize_checks(roll, ["unit", "e2e"])
    check("status: a re-run's latest result wins", text.startswith("1 pass 1 running 1 fail 1 skipped"), True)
    check("status: required still running", req, "running")
    check("status: a required job that never ran", summarize_checks(roll, ["unit", "build"])[1], "missing")
    dup = [{"__typename": "CheckRun", "name": "e2e", "status": "IN_PROGRESS", "conclusion": "", "startedAt": "2026-10-25T09:00:00Z"},
           {"__typename": "CheckRun", "name": "e2e", "status": "COMPLETED", "conclusion": "SKIPPED", "startedAt": "2026-10-25T09:05:00Z"}]
    check("status: a skipped duplicate does not hide a running check", summarize_checks(dup, ["e2e"])[1], "running")
    check("status: required all green", summarize_checks(roll[:2], ["unit"])[1], "green")

    # held work
    ok_gate, tight_full = {"code": 0, "room_heavy": 2}, {"code": 1, "room_heavy": 0}
    held = {"P-12": {"blocked_by": ["P-11"], "since": "2026-11-19T08:00:00Z"}, "P-20": {"blocked_by": ["P-18", "P-19"]}}
    prs = [{"number": 211, "tickets": ["P-11"], "branch": "feat/P-11-a", "labels": ["qa-approved"]},
           {"number": 215, "tickets": ["P-11", "P-18"], "branch": "release/group-1", "labels": []}]
    h = held_work(held, prs, 1, ok_gate)
    check("held: a blocker in an open PR, a free slot and room give a line", [x["ticket"] for x in h], ["P-12"])
    check("held: it names the blocker PR, the group and the branch to stack on",
          (h[0]["blockers"][0]["pr"], h[0]["blockers"][0]["group"], h[0]["stack_on"]), (211, 215, "feat/P-11-a"))
    check("held: a blocker with no pushed branch gives no line", "P-20" in [x["ticket"] for x in h], False)
    check("held: no free slot gives no line", held_work(held, prs, 0, ok_gate), [])
    check("held: tight with no room gives no line", held_work(held, prs, 1, tight_full), [])
    check("held: tight with room gives a line", len(held_work(held, prs, 1, {"code": 1, "room_heavy": 1})), 1)
    check("held: closed gives no line", held_work(held, prs, 1, {"code": 2, "room_heavy": 3}), [])
    check("held: critical gives no line", held_work(held, prs, 1, {"code": 3, "room_heavy": 0}), [])
    both = prs + [{"number": 219, "tickets": ["P-19"], "branch": "feat/P-19-c", "labels": []}]
    h2 = {x["ticket"]: x for x in held_work(held, both, 2, ok_gate)}
    check("held: a blocker only in a group PR stacks on the group branch", h2["P-20"]["stack_on"], "release/group-1")
    check("held: a second blocker branch is merged in", h2["P-20"]["merge_in"], ["feat/P-19-c"])
    check("held: a ticket with a running lane is not held", held_work(held, prs, 1, ok_gate, ["codex:x engineer P-12 · 3m"]), [])
    check("held: P-1 in a lane does not hide P-12", len(held_work(held, prs, 1, ok_gate, ["codex:x engineer P-1 · 3m"])), 1)
    started = prs + [{"number": 230, "tickets": ["P-12"], "branch": "feat/P-12-b", "labels": []}]
    check("held: a ticket with its own PR is pruned", sorted(prune_held(held, started)), ["P-20"])
    check("held: free slots ignore the shared row", free_slot_count(["A free", "B busy (api · x)", "shared up (owner's, never assigned)"]), 1)
    lines = held_lines(h, 1)
    check("held: the line names ticket, PR and branch", ("P-12 held by P-11 #211 approved in group #215" in lines[1],
                                                          "stack on feat/P-11-a" in lines[1]), (True, True))
    check("held: nothing held prints nothing", held_lines([], 2), [])
    import tempfile
    d = tempfile.mkdtemp(prefix="fleetstatus-selftest-")
    hp, sp = held_paths(d, "st")
    save_held(hp, held)
    check("held: the record round trips", load_held(hp), held)
    record_seen(sp, h, 1, now=1_000_000)
    check("held: a sighting is logged", json.loads(open(sp).readline())["ticket"], "P-12")
