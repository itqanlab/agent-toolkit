#!/usr/bin/env python3
"""fleetcost — what each ticket really cost and how long it took, read from the sessions.

The `tokens` number the PM logs for a Claude spawn is the size of the agent's last call, not
what it spent (measured 2026-10-25: 30 to 100 times less). This module reads the real usage
from Claude Code's session files, adds the lanes' usage from their result files, takes merge
times from GitHub, and prices it all with the registry's `prices` block.

  run-lane.sh cost [--cwd REPO] [--since ISO] [--until ISO]     window report
  run-lane.sh cost --ticket PROJ-12                              one ticket's timeline
  run-lane.sh cost --json                                        the same, as data
  run-lane.sh cost --backfill                                    true usage onto the log's Claude rows

Standard library only. Python 3.9. Never prints secrets: it reads usage numbers, tool names,
the first lines of a brief, and agent descriptions.
"""
import datetime, glob, hashlib, json, os, re, subprocess, sys

CACHE_VERSION = 2
REWRITE_GAP_S = 300          # the default prompt cache lives 5 minutes
REWRITE_SHARE = 0.6          # a write of more than this share of the previous context is a rewrite
BUCKET_S = 600               # activity is tracked in 10-minute buckets
NON_CLAUDE_EXECUTORS = ("codex", "opencode", "claude-ollama")
# A main session that shows any of these ran the fleet (PM, solo-ship, or lanes only).
FLEET_HINTS = ("team-pm", "plane-fleet", "subagent_type", "run-lane.sh", "team-engineer", "team-tester", "solo-ship")


# ---------------------------------------------------------------- small helpers
def parse_ts(s):
    if not s:
        return None
    try:
        d = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.astimezone()


def epoch(s):
    d = parse_ts(s)
    return d.timestamp() if d else None


def quantiles(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    pick = lambda q: v[min(len(v) - 1, int(q * len(v)))]
    return {"n": len(v), "median": pick(0.5), "p75": pick(0.75), "p90": pick(0.9), "mean": sum(v) / len(v)}


def money(x):
    return "—" if x is None else (f"${x:,.0f}" if abs(x) >= 100 else f"${x:,.2f}")


def hours(x):
    return "—" if x is None else f"{x:.1f}h"


def ktok(n):
    if n is None:
        return "—"
    return f"{n / 1e6:,.1f}M" if n >= 1e6 else f"{n / 1e3:,.0f}k"


# ---------------------------------------------------------------- prices
def model_price(prices, model):
    """(input, output, cache_read) USD per 1M tokens, or None. Exact id first, then the longest
    key the id starts with, so claude-haiku-4-5-20251001 finds claude-haiku-4-5."""
    table = (prices or {}).get("models") or {}
    if not model:
        return None
    p = table.get(model)
    if p is None:
        keys = [k for k in table if not k.startswith("$") and model.startswith(k)]
        p = table[max(keys, key=len)] if keys else None
    if not isinstance(p, dict) or p.get("input") is None or p.get("output") is None:
        return None
    cr = p.get("cache_read")
    return float(p["input"]), float(p["output"]), float(cr if cr is not None else p["input"] * 0.1)


def usd(prices, model, u):
    """u = [input, cache_write_5m, cache_write_1h, cache_read, output] tokens."""
    p = model_price(prices, model)
    if p is None:
        return None
    i, o, r = p
    mult = (prices or {}).get("cache_write_multiplier") or {}
    m5, m1 = float(mult.get("5m", 1.25)), float(mult.get("1h", 2.0))
    return (u[0] * i + u[1] * i * m5 + u[2] * i * m1 + u[3] * r + u[4] * o) / 1e6


def usd_by_model(prices, by_model):
    """Sum over {model: [5 token counts, ...]}; returns (usd, {model: tokens} for unpriced)."""
    total, unpriced = 0.0, {}
    for model, u in (by_model or {}).items():
        c = usd(prices, model, u)
        if c is None:
            unpriced[model] = unpriced.get(model, 0) + sum(u[:5])
        else:
            total += c
    return total, unpriced


# ---------------------------------------------------------------- tool-call classes
_WRITE = re.compile(r"cat >>? ?(?!/tmp|/private/tmp|/dev/)|open\([^)]*,\s*['\"][wa]['\"]|\.write\(|sed -i|apply_patch|perl -pi|\btee (?!/tmp)")
_RUN = re.compile(r"\b(nx|jest|vitest|playwright|pytest|tsc|prisma|psql|docker|npm (run|test)|pnpm|yarn|npx|node|cargo|go (test|build)|make)\b|curl [^|]*localhost")
_GIT = re.compile(r"^\s*(cd [^&;]*(&&|;)\s*)?(git|gh)\b")
_WAIT = re.compile(r"\bsleep\b|\buntil\b|\bwhile\b|/tasks/[^ ]*\.output")
_READ = re.compile(r"^\s*(cd [^&;]*(&&|;)\s*)?([A-Z_]+=\S+\s*;?\s*)*(sed -n|grep|rg|cat|head|tail|wc|ls|find|awk|jq|diff|for )")


def classify(name, text):
    """One tool call -> an activity class: read, write, run, git, plane, spawn, wait, other."""
    if name in ("Agent", "Task"):
        return "spawn"
    if name.startswith("mcp__plane"):
        return "plane"
    if name in ("Read", "Grep", "Glob", "LS"):
        return "read"
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "write"
    if name in ("Monitor", "TaskOutput", "TaskStop", "ScheduleWakeup", "SendMessage"):
        return "wait"
    if name != "Bash":
        return "other"
    if _WRITE.search(text) and "<<<<<<<" not in text:
        return "write"
    if _RUN.search(text):
        return "run"
    if _GIT.search(text):
        return "git"
    if _WAIT.search(text):
        return "wait"
    if _READ.search(text):
        return "read"
    return "other"


def role_of(agent_type, description):
    """Role from the agent type and the description the PM gave the spawn. Convention
    (team-pm §3): '<role> <TICKET> [note]', role one of engineer, rework, tester, retest,
    planner, plane, merge, notify, scan; anything else is 'other'."""
    d = (description or "").lower()
    t = (agent_type or "").lower()
    if re.search(r"\b(rework\d*|amend|fix-forward)\b|\bfix\b(?!.*\b(ci|group|e2e)\b)", d):
        return "rework"
    if re.search(r"\bre-?test(er)?\b|\bretest\d?\b", d):
        return "retest"
    if t == "fleet-tester" or re.search(r"\btest(er)?\b", d):
        return "tester"
    if t == "fleet-planner" or re.search(r"\bplan(ner)?\b", d):
        return "planner"
    if t == "fleet-plane" or re.search(r"\b(ticket writer|file the plan|board)\b", d):
        return "plane"
    if t == "fleet-engineer" or re.search(r"\b(engineer|build|implement|finish)\b", d):
        return "engineer"
    if re.search(r"\b(group|merge|rebase|ci|sync)\b", d):
        return "merge"
    if re.search(r"\b(client|notify|whatsapp|done notes)\b", d):
        return "notify"
    if re.search(r"\b(scan|triage|count|map|list|find|extract)\b", d) or t == "explore":
        return "scan"
    return "other"


# ---------------------------------------------------------------- transcript discovery
def claude_projects_root():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(base, "projects")


def encode_path(path):
    """Claude Code names a project folder after its path, every non-alphanumeric as '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def project_dirs(repo_root, extra=(), root=None):
    """Folders under the Claude projects root that hold this repo's sessions: the repo path
    itself, and any path inside it (worktrees, subfolders). A folder that only shares a prefix
    (a sibling repo named repo-mobile) is kept only if the rest names a real path in the repo.
    `extra` adds folder names or globs, for a repo that moved since its sessions were written."""
    root = root or claude_projects_root()
    if not os.path.isdir(root):
        return []
    want = {encode_path(p) for p in {repo_root, os.path.realpath(repo_root)} if p}
    out = []
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue
        hit = name in want
        for w in want:
            if not hit and name.startswith(w + "-"):
                rest = name[len(w) + 1:]
                # '--claude-worktrees-x' (a dot folder) or a real subfolder of the repo
                if rest.startswith("-") or _rest_exists(repo_root, rest):
                    hit = True
        if hit:
            out.append(full)
    for e in extra or ():
        for full in glob.glob(e if os.path.isabs(e) else os.path.join(root, e)):
            if os.path.isdir(full) and full not in out:
                out.append(full)
    return out


def _rest_exists(base, rest):
    """Does '-'-joined `rest` name a path under base, with each '-' a '/' or a literal '-'?"""
    parts = rest.split("-")

    def walk(prefix, i):
        if i == len(parts):
            return True
        for j in range(i + 1, len(parts) + 1):
            cand = os.path.join(prefix, "-".join(parts[i:j]))
            if os.path.exists(cand) and walk(cand, j):
                return True
        return False
    return walk(base, 0)


# ---------------------------------------------------------------- one session file -> summary
def _usage_tokens(u):
    cc = u.get("cache_creation") or {}
    c5 = cc.get("ephemeral_5m_input_tokens")
    c1 = cc.get("ephemeral_1h_input_tokens")
    if c5 is None and c1 is None:
        c5, c1 = u.get("cache_creation_input_tokens") or 0, 0
    return [u.get("input_tokens") or 0, c5 or 0, c1 or 0, u.get("cache_read_input_tokens") or 0,
            u.get("output_tokens") or 0]


def _add(acc, key, u):
    a = acc.setdefault(key, [0, 0, 0, 0, 0, 0])
    for i in range(5):
        a[i] += u[i]
    a[5] += 1


def summarize_file(path):
    """Read one Claude Code session file. Assistant lines are deduplicated by message id: one
    API call is written as one line per content block, each carrying the same usage."""
    calls, order = {}, []
    prompt = None
    fleet_hint = False
    first_ts = last_ts = None
    with open(path, errors="replace") as f:
        for line in f:
            is_asst = '"type":"assistant"' in line or '"type": "assistant"' in line
            if not fleet_hint and any(h in line for h in FLEET_HINTS):
                fleet_hint = True
            if not is_asst and (prompt is not None or ('"type":"user"' not in line and '"type": "user"' not in line)):
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("isSidechain") and not path.split(os.sep)[-2] == "subagents":
                continue  # old layout: sidechain lines inside the main file belong to an agent
            ts = r.get("timestamp")
            if r.get("type") == "user" and prompt is None:
                c = (r.get("message") or {}).get("content")
                prompt = (c if isinstance(c, str) else json.dumps(c))[:2000]
                first_ts = first_ts or ts
                continue
            if r.get("type") != "assistant":
                continue
            m = r.get("message") or {}
            mid = m.get("id") or r.get("uuid")
            if mid not in calls:
                order.append(mid)
                calls[mid] = {"model": m.get("model"), "usage": None, "tools": [], "ts": ts}
            c = calls[mid]
            if m.get("usage"):
                c["usage"] = m["usage"]
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    text = inp.get("command") if isinstance(inp, dict) and isinstance(inp.get("command"), str) else json.dumps(inp)
                    c["tools"].append((b.get("name") or "", text[:2000]))
            first_ts = first_ts or ts
            last_ts = ts or last_ts
    by_model, by_day, activity, rewrites = {}, {}, {}, {}
    buckets = set()
    first_ctx = end_ctx = None
    prev_ctx, prev_t = 0, None
    spawns = 0
    for mid in order:
        c = calls[mid]
        if not c["usage"]:
            continue
        model = c["model"] or "?"
        if model == "<synthetic>":
            continue
        u = _usage_tokens(c["usage"])
        _add(by_model, model, u)
        t = epoch(c["ts"])
        day = (c["ts"] or "")[:10]
        _add(by_day.setdefault(day, {}), model, u)
        if t:
            buckets.add(int(t // BUCKET_S))
        ctx = u[0] + u[1] + u[2] + u[3]
        if first_ctx is None:
            first_ctx = ctx
        end_ctx = ctx
        gap = (t - prev_t) if (t and prev_t) else None
        if prev_ctx > 20000 and (u[1] + u[2]) > REWRITE_SHARE * prev_ctx and gap is not None and gap >= REWRITE_GAP_S:
            _add(rewrites, model, [0, u[1], u[2], 0, 0])
        prev_ctx, prev_t = ctx, t or prev_t
        classes = [classify(n, x) for n, x in c["tools"]] or ["text"]
        spawns += classes.count("spawn")
        share = [x / len(classes) for x in u]
        for cl in classes:
            a = activity.setdefault(cl, {})
            _add(a, model, share)
    return {"v": CACHE_VERSION, "calls": sum(v[5] for v in by_model.values()), "by_model": by_model,
            "by_day": by_day, "activity": activity, "rewrites": rewrites, "first_ts": first_ts,
            "last_ts": last_ts, "first_ctx": first_ctx, "end_ctx": end_ctx, "prompt": prompt,
            "fleet_hint": fleet_hint, "spawns": spawns, "buckets": sorted(buckets)}


def cached_summary(path, cache_dir):
    """A session's summary, from the cache when the file is unchanged. Agents also keep their
    .meta.json in it. Claude Code deletes session files after cleanupPeriodDays (30 by
    default), and the cache is then the only record, so entries are never pruned."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = [st.st_size, int(st.st_mtime)]
    cpath = os.path.join(cache_dir, hashlib.sha1(path.encode()).hexdigest() + ".json")
    try:
        with open(cpath) as f:
            c = json.load(f)
        if c.get("key") == key and c.get("summary", {}).get("v") == CACHE_VERSION:
            return c["summary"]
    except (OSError, ValueError):
        pass
    s = summarize_file(path)
    if os.path.basename(os.path.dirname(path)) == "subagents":
        try:
            with open(path[:-6] + ".meta.json") as f:
                s["meta"] = json.load(f)
        except (OSError, ValueError):
            s["meta"] = {}
    try:
        os.makedirs(cache_dir, exist_ok=True)
        tmp = cpath + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"key": key, "path": path, "summary": s}, f, separators=(",", ":"))
        os.replace(tmp, cpath)
    except OSError:
        pass
    return s


# ---------------------------------------------------------------- collect
def ticket_re(identifier):
    ident = re.escape(identifier) if identifier else r"[A-Z][A-Z0-9]{1,9}"
    return re.compile(r"\b(" + ident + r"-\d+)\b")


def archived(dirs, cache_dir, seen):
    """Cached summaries whose session file is gone: (path, summary) for the given folders."""
    roots = tuple(d.rstrip(os.sep) + os.sep for d in dirs)
    out = []
    for c in glob.glob(os.path.join(cache_dir, "*.json")):
        try:
            with open(c) as f:
                e = json.load(f)
        except (OSError, ValueError):
            continue
        p = e.get("path") or ""
        if p.startswith(roots) and p not in seen and (e.get("summary") or {}).get("v") == CACHE_VERSION:
            out.append((p, e["summary"]))
    return out


def collect(dirs, cache_dir, identifier=None):
    """All sessions in the given project folders: main sessions and their agents, including
    sessions whose files Claude Code has since deleted but the cache still holds."""
    tre = ticket_re(identifier)
    mains, agents = [], []
    found = []
    for d in dirs:
        for p in sorted(glob.glob(os.path.join(d, "*.jsonl")) + glob.glob(os.path.join(d, "*", "subagents", "agent-*.jsonl"))):
            found.append((p, cached_summary(p, cache_dir)))
    found += archived(dirs, cache_dir, {p for p, _ in found})
    for p, s in found:
        if not s or not s["calls"]:
            continue
        if os.path.basename(os.path.dirname(p)) != "subagents":
            s.update(path=p, session=os.path.basename(p)[:-6])
            mains.append(s)
            continue
        meta = s.get("meta") or {}
        desc = meta.get("description") or ""
        tickets = list(dict.fromkeys(tre.findall(desc))) or list(dict.fromkeys(tre.findall((s.get("prompt") or "")[:1500])))
        s.update(path=p, session=p.split(os.sep)[-3], agent_id=os.path.basename(p)[6:-6],
                 agent_type=meta.get("agentType"), description=desc, meta_model=meta.get("model"),
                 tickets=tickets, role=role_of(meta.get("agentType"), desc))
        agents.append(s)
    spawned = {a["session"] for a in agents}
    for m in mains:
        models = [k for k in m["by_model"] if k.startswith("claude")]
        if not models:
            m["kind"] = "lane"       # claude -p on another provider: counted from the lane's own result
        elif m["session"] in spawned or m["fleet_hint"]:
            m["kind"] = "pm"
        else:
            m["kind"] = "other"
    return mains, agents


def lane_sessions(rows, project):
    """Lane spawns from the outcomes log: identity, duration and usage from the row."""
    out = []
    for r in rows:
        if r.get("type", "spawn") != "spawn" or r.get("executor") not in NON_CLAUDE_EXECUTORS:
            continue
        if project and r.get("project") != project:
            continue
        end = epoch(r.get("ts"))
        dur = r.get("duration_ms") if isinstance(r.get("duration_ms"), (int, float)) else None
        start = (end - dur / 1000) if (end and dur) else end
        inp = r.get("input_tokens") or 0
        cached = r.get("cached_input_tokens") or 0
        role = r.get("role") or "other"
        if role == "engineer" and r.get("task_kind") == "rework":
            role = "rework"
        if role == "tester" and r.get("task_kind") == "retest":
            role = "retest"
        out.append({"ticket": r.get("ticket"), "role": role, "executor": r.get("executor"), "model": r.get("model"),
                    "start": start, "end": end, "outcome": r.get("outcome"),
                    "usage": [inp - cached, 0, 0, cached, r.get("output_tokens") or 0],
                    "tokens": (inp + (r.get("output_tokens") or 0)) if (inp or r.get("output_tokens")) else r.get("tokens")})
    return out


# ---------------------------------------------------------------- merges
def merged_prs(repo, trunk, since_day):
    cmd = ["gh", "pr", "list", "--state", "merged", "--limit", "1000", "--json",
           "number,title,headRefName,baseRefName,createdAt,mergedAt,additions,deletions,changedFiles"]
    if trunk:
        cmd += ["--base", trunk]
    if since_day:
        cmd += ["--search", f"merged:>={since_day}"]
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"gh failed: {e}"
    if r.returncode:
        return None, "gh failed: " + (r.stderr.strip().splitlines() or ["?"])[-1]
    try:
        prs = json.loads(r.stdout)
    except ValueError:
        return None, "gh returned no JSON"
    return prs, ("only the latest 1000 merges were read; use a shorter window" if len(prs) >= 1000 else None)


# ---------------------------------------------------------------- per ticket
def build_tickets(agents, lanes, prs, prices, identifier, t0, t1, log_rows):
    tre = ticket_re(identifier)
    tickets = {}

    def slot(t):
        return tickets.setdefault(t, {"ticket": t, "sessions": [], "usd": {}, "unpriced": {}, "first": None})

    for a in agents:
        start, end = epoch(a["first_ts"]), epoch(a["last_ts"])
        if start is None or (t0 and start < t0) or (t1 and start >= t1):
            continue
        cost, unp = usd_by_model(prices, a["by_model"])
        for t in a["tickets"]:
            x = slot(t)
            share = 1.0 / len(a["tickets"])
            x["sessions"].append({"start": start, "end": end, "role": a["role"], "who": a.get("agent_type") or "agent",
                                  "model": a.get("meta_model") or max(a["by_model"], key=lambda k: a["by_model"][k][5]),
                                  "usd": cost * share, "calls": a["calls"], "agent_id": a["agent_id"],
                                  "description": a.get("description")})
            x["usd"][a["role"]] = x["usd"].get(a["role"], 0) + cost * share
            for k, v in unp.items():
                x["unpriced"][k] = x["unpriced"].get(k, 0) + v * share
    for l in lanes:
        if not l["ticket"] or l["start"] is None or (t0 and l["start"] < t0) or (t1 and l["start"] >= t1):
            continue
        x = slot(l["ticket"])
        c = usd(prices, l["model"], l["usage"])
        x["sessions"].append({"start": l["start"], "end": l["end"], "role": l["role"], "who": l["executor"],
                              "model": l["model"], "usd": c, "tokens": l["tokens"], "outcome": l["outcome"]})
        if c is not None:
            x["usd"][l["role"]] = x["usd"].get(l["role"], 0) + c
        elif l["tokens"]:
            key = f"{l['executor']}:{l['model']}"
            x["unpriced"][key] = x["unpriced"].get(key, 0) + l["tokens"]
    by_ticket_prs = {}
    for p in prs or []:
        for t in set(tre.findall((p.get("headRefName") or "") + " " + (p.get("title") or ""))):
            by_ticket_prs.setdefault(t, []).append(p)
    causes = {}
    for r in log_rows:
        if r.get("outcome") == "verify_fail" and r.get("ticket"):
            causes.setdefault(r["ticket"], []).append(r.get("fail_cause") or r.get("failure_cause") or "unknown")
    for t, x in tickets.items():
        x["sessions"].sort(key=lambda s: s["start"])
        x["first"] = x["sessions"][0]["start"]
        x["cost"] = sum(x["usd"].values())
        x["rework"] = sum(1 for s in x["sessions"] if s["role"] == "rework")
        x["fail_causes"] = causes.get(t, [])
        ps = sorted((p for p in by_ticket_prs.get(t, []) if (epoch(p.get("mergedAt")) or 0) >= x["first"]),
                    key=lambda p: p.get("mergedAt"))
        # the ticket's own PR, not the group PR that merged with it
        own = [p for p in ps if not (p.get("headRefName") or "").startswith(("release/", "group/"))] or ps
        if own:
            p = own[0]
            x["pr"] = p.get("number")
            x["merged"] = epoch(p.get("mergedAt"))
            x["pr_opened"] = epoch(p.get("createdAt"))
            x["lines"] = (p.get("additions") or 0) + (p.get("deletions") or 0)
            x["files"] = p.get("changedFiles")
            x["cycle_h"] = (x["merged"] - x["first"]) / 3600
            iv = []
            for s in x["sessions"]:
                a, b = s["start"], min(s["end"] or s["start"], x["merged"])
                if b > a:
                    iv.append([a, b])
            iv.sort()
            merged = []
            for a, b in iv:
                if merged and a <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            x["active_h"] = sum(b - a for a, b in merged) / 3600
    return tickets


# ---------------------------------------------------------------- report
def _sum_usage(items):
    acc = {}
    for by_model in items:
        for model, u in by_model.items():
            a = acc.setdefault(model, [0, 0, 0, 0, 0, 0])
            for i in range(6):
                a[i] += u[i]
    return acc


def _token_split(prices, by_model):
    """USD by token type: cache read, cache write, output, input."""
    out = {"cache read": 0.0, "cache write": 0.0, "output": 0.0, "input": 0.0}
    mult = (prices or {}).get("cache_write_multiplier") or {}
    for model, u in by_model.items():
        p = model_price(prices, model)
        if not p:
            continue
        i, o, r = p
        out["input"] += u[0] * i / 1e6
        out["cache write"] += (u[1] * float(mult.get("5m", 1.25)) + u[2] * float(mult.get("1h", 2.0))) * i / 1e6
        out["cache read"] += u[3] * r / 1e6
        out["output"] += u[4] * o / 1e6
    return out


def window(since, until):
    t0 = epoch(since) if since else None
    t1 = epoch(until) if until else None
    if since and t0 is None:
        raise SystemExit(f"fleetcost: --since {since!r} is not an ISO time")
    return t0, t1


def analyse(mains, agents, lanes, prs, prices, identifier, since, until, log_rows):
    t0, t1 = window(since, until)
    tickets = build_tickets(agents, lanes, prs, prices, identifier, t0, t1, log_rows)
    in_win = lambda s: s and (not t0 or epoch(s) >= t0) and (not t1 or epoch(s) < t1)
    day0 = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc).strftime("%Y-%m-%d") if t0 else ""
    day1 = datetime.datetime.fromtimestamp(t1, datetime.timezone.utc).strftime("%Y-%m-%d") if t1 else "9999"
    pm = [m for m in mains if m["kind"] == "pm"]
    other = [m for m in mains if m["kind"] == "other"]
    pm_usage = _sum_usage(u for m in pm for d, u in m["by_day"].items() if day0 <= d < day1)
    other_usage = _sum_usage(u for m in other for d, u in m["by_day"].items() if day0 <= d < day1)
    win_agents = [a for a in agents if in_win(a["first_ts"])]
    agent_usage = _sum_usage(a["by_model"] for a in win_agents)
    pm_usd, pm_unpriced = usd_by_model(prices, pm_usage)
    agent_usd, agent_unpriced = usd_by_model(prices, agent_usage)
    other_usd, _ = usd_by_model(prices, other_usage)
    merged = [x for x in tickets.values() if x.get("merged")]
    lane_tok = {}
    for l in lanes:
        if l["start"] and (not t0 or l["start"] >= t0) and (not t1 or l["start"] < t1) and l["tokens"]:
            k = f"{l['executor']}:{l['model']}"
            lane_tok[k] = lane_tok.get(k, 0) + l["tokens"]
    # fleet running: any PM call or agent call in a 10-minute bucket, plus lane spans
    alive = set()
    for m in pm:
        alive.update(m["buckets"])
    for a in win_agents:
        alive.update(a["buckets"])
    for l in lanes:
        if l["start"] and l["end"]:
            alive.update(range(int(l["start"] // BUCKET_S), int(l["end"] // BUCKET_S) + 1))
    on = off = 0
    for x in merged:
        for b in range(int(x["first"] // BUCKET_S), int(x["merged"] // BUCKET_S)):
            if b in alive:
                on += 1
            else:
                off += 1
    # agents: rewrites and first-call context by agent type
    rew = _sum_usage(a["rewrites"] for a in win_agents)
    rew_usd, _ = usd_by_model(prices, rew)
    first_ctx = {}
    for a in win_agents:
        if a.get("first_ctx"):
            first_ctx.setdefault(a.get("agent_type") or "?", []).append(a["first_ctx"])
    pm_act = {}
    for m in pm:
        if not any(day0 <= d < day1 for d in m["by_day"]):
            continue
        for cl, bm in m["activity"].items():
            pm_act[cl] = pm_act.get(cl, 0) + usd_by_model(prices, bm)[0]
    pm_calls = sum(u[5] for u in pm_usage.values())
    pm_ctx = (sum(u[0] + u[1] + u[2] + u[3] for u in pm_usage.values()) / pm_calls) if pm_calls else None
    roles = {}
    for x in merged:
        for role, v in x["usd"].items():
            roles[role] = roles.get(role, 0) + v
    return {
        "since": since, "until": until, "tickets": tickets, "merged": merged,
        "pm": {"sessions": len(pm), "usd": pm_usd, "unpriced": pm_unpriced, "calls": pm_calls,
               "ctx_per_call": pm_ctx, "activity": pm_act, "split": _token_split(prices, pm_usage)},
        "agents": {"sessions": len(win_agents), "usd": agent_usd, "unpriced": agent_unpriced,
                   "split": _token_split(prices, agent_usage), "rewrite_usd": rew_usd,
                   "rewrite_calls": sum(u[5] for u in rew.values()),
                   "first_ctx": {k: quantiles(v) for k, v in first_ctx.items()}},
        "other": {"sessions": len(other), "usd": other_usd},
        "lanes": lane_tok, "roles": roles,
        "fleet_running_share": (on / (on + off)) if (on + off) else None,
    }


def render(res, project, prices, prs_error=None, sources=None):
    L = []
    merged = res["merged"]
    n = len(merged)
    w = f"{res['since'] or 'start'} to {res['until'] or 'now'}"
    L.append(f"Fleet cost · {project} · {w}")
    if sources:
        L.append(f"  sessions from {len(sources)} project folder(s); "
                 f"{res['pm']['sessions']} PM, {res['agents']['sessions']} agent, {res['other']['sessions']} other (not fleet)")
    L.append(f"  prices: {(prices or {}).get('source', 'none')} — API list prices to compare options; plans bill differently")
    if prs_error:
        L.append(f"  merges: {prs_error}")
    L.append("")
    total = res["pm"]["usd"] + res["agents"]["usd"]
    L.append(f"Spend: {money(total)} = agents {money(res['agents']['usd'])} + PM {money(res['pm']['usd'])}"
             + (f"   (other sessions in this repo, not counted: {money(res['other']['usd'])})" if res["other"]["sessions"] else ""))
    unp = dict(res["agents"]["unpriced"])
    for k, v in res["pm"]["unpriced"].items():
        unp[k] = unp.get(k, 0) + v
    for k, v in res["lanes"].items():
        unp[k] = unp.get(k, 0) + v
    if unp:
        L.append("  no price, tokens only: " + ", ".join(f"{k} {ktok(v)}" for k, v in sorted(unp.items(), key=lambda kv: -kv[1])))
    L.append("")
    if n:
        pm_share = res["pm"]["usd"] / n
        L.append(f"Merged tickets: {n} (first spawn in the window, merged into trunk)")
        rows = [("agent cost", [x["cost"] for x in merged], money),
                ("agent + PM share", [x["cost"] + pm_share for x in merged], money),
                ("first spawn → merge", [x["cycle_h"] for x in merged], hours),
                ("agents working", [x.get("active_h") for x in merged], hours)]
        L.append(f"  {'per ticket':<22}{'median':>9}{'p75':>9}{'p90':>9}{'mean':>9}")
        for name, vals, f in rows:
            q = quantiles(vals)
            if q:
                L.append(f"  {name:<22}{f(q['median']):>9}{f(q['p75']):>9}{f(q['p90']):>9}{f(q['mean']):>9}")
        if res["fleet_running_share"] is not None:
            L.append(f"  no fleet session was running for {100 * (1 - res['fleet_running_share']):.0f}% of that time")
        L.append("")
        tot_roles = sum(res["roles"].values()) or 1
        L.append("Agent cost of merged tickets, by role")
        for role, v in sorted(res["roles"].items(), key=lambda kv: -kv[1]):
            L.append(f"  {role:<10}{money(v):>9}  {100 * v / tot_roles:4.0f}%")
        L.append("")
        L.append(f"  {'rework rounds':<15}{'tickets':>8}{'cost mean':>11}{'cycle median':>14}")
        for name, sel in (("0", lambda x: x["rework"] == 0), ("1", lambda x: x["rework"] == 1), ("2+", lambda x: x["rework"] >= 2)):
            g = [x for x in merged if sel(x)]
            if g:
                L.append(f"  {name:<15}{len(g):>8}{money(sum(x['cost'] for x in g) / len(g)):>11}"
                         f"{hours(quantiles([x['cycle_h'] for x in g])['median']):>14}")
        causes = {}
        for x in merged:
            for c in x["fail_causes"]:
                causes[c] = causes.get(c, 0) + 1
        if causes:
            L.append("  test failures by cause: " + ", ".join(f"{k} {v}" for k, v in sorted(causes.items(), key=lambda kv: -kv[1])))
        L.append("")
    else:
        L.append("Merged tickets: none in the window" + (" (no merge data)" if prs_error else ""))
        L.append("")
    a = res["agents"]
    sp = a["split"]
    st = sum(sp.values()) or 1
    L.append("Where agent money goes")
    L.append("  " + " · ".join(f"{k} {100 * v / st:.0f}%" for k, v in sorted(sp.items(), key=lambda kv: -kv[1]) if v))
    if a["usd"]:
        L.append(f"  whole-context cache rewrites after a wait of 5+ min: {a['rewrite_calls']} calls, "
                 f"{money(a['rewrite_usd'])} ({100 * a['rewrite_usd'] / a['usd']:.0f}% of agent cost)")
    fc = [(k, q) for k, q in a["first_ctx"].items() if q]
    if fc:
        L.append("  context at an agent's first call, median: " + ", ".join(
            f"{k} {ktok(q['median'])} (n={q['n']})" for k, q in sorted(fc, key=lambda kv: -kv[1]["n"])[:6]))
    p = res["pm"]
    if p["sessions"]:
        L.append("")
        L.append("PM sessions")
        L.append(f"  {p['calls']:,} calls" + (f", {p['calls'] / n:.0f} per merged ticket" if n else "")
                 + (f"; average context per call {ktok(p['ctx_per_call'])}" if p["ctx_per_call"] else ""))
        at = sum(p["activity"].values()) or 1
        L.append("  by activity: " + " · ".join(f"{k} {100 * v / at:.0f}%" for k, v in sorted(p["activity"].items(), key=lambda kv: -kv[1]) if v / at >= 0.01))
    return "\n".join(L)


def render_ticket(x):
    tz = lambda t: datetime.datetime.fromtimestamp(t).strftime("%m-%d %H:%M") if t else "?"
    L = [f"{x['ticket']} · first spawn {tz(x['first'])}"
         + (f" · PR #{x['pr']} opened {tz(x.get('pr_opened'))}, merged {tz(x['merged'])} · {hours(x['cycle_h'])}, "
            f"agents working {hours(x.get('active_h'))}" if x.get("merged") else " · not merged")
         + f" · {money(x['cost'])}" + ("".join(f" + {k} {ktok(v)} tokens" for k, v in x["unpriced"].items()))]
    for s in x["sessions"]:
        extra = f"{s.get('calls', '')} calls" if s.get("calls") else (f"{ktok(s.get('tokens'))} tokens" if s.get("tokens") else "")
        L.append(f"  {tz(s['start'])} → {tz(s['end'])}  {s['role']:<9}{s['who']:<17}{str(s['model'])[:18]:<19}"
                 f"{money(s['usd']):>9}  {extra:<14}{s.get('outcome') or '':<13}  {(s.get('description') or '')[:50]}")
    if x["fail_causes"]:
        L.append("  test failures: " + ", ".join(x["fail_causes"]))
    return "\n".join(L)


# ---------------------------------------------------------------- backfill
def backfill_rows(agents, rows, prices, project):
    """Usage rows for Claude spawn rows that carry no real usage. A row matches the agent with
    its agent_id, else the agent of the same ticket and role that ended closest before the row
    was written (within 30 minutes)."""
    by_id = {a["agent_id"]: a for a in agents}
    out = []
    used = set()
    for r in rows:
        if r.get("type", "spawn") != "spawn" or (r.get("executor") or "claude") != "claude" or r.get("usage_only"):
            continue
        if project and r.get("project") != project:
            continue
        if r.get("role") == "pm" or isinstance(r.get("input_tokens"), (int, float)) or r.get("usage_source") == "transcript":
            continue
        a = by_id.get(r.get("agent_id"))
        if a is None:
            t = epoch(r.get("ts"))
            best = None
            for c in agents:
                if c["agent_id"] in used or r.get("ticket") not in c["tickets"] or not c["last_ts"] or t is None:
                    continue
                if _role_family(c["role"]) != _role_family(r.get("role"), r.get("task_kind")):
                    continue
                d = t - epoch(c["last_ts"])
                if -120 <= d <= 1800 and (best is None or abs(d) < best[0]):
                    best = (abs(d), c)
            a = best[1] if best else None
        if a is None:
            continue
        used.add(a["agent_id"])
        u = _sum_usage([a["by_model"]])
        tot = [sum(v[i] for v in u.values()) for i in range(5)]
        cost, _ = usd_by_model(prices, a["by_model"])
        out.append({"type": "spawn", "usage_only": True, "for_ts": r.get("ts"), "ts": r.get("ts"),
                    "project": r.get("project"), "ticket": r.get("ticket"), "role": r.get("role"),
                    "executor": "claude", "model": r.get("model"), "outcome": r.get("outcome"),
                    "input_tokens": tot[0] + tot[1] + tot[2] + tot[3], "cached_input_tokens": tot[3],
                    "output_tokens": tot[4], "usd": round(cost, 4), "agent_id": a["agent_id"],
                    "usage_source": "transcript"})
    return out


def _role_family(role, kind=None):
    if role in ("engineer", "rework") or kind == "rework":
        return "engineer"
    if role in ("tester", "retest", "verifier-legacy"):
        return "tester"
    return role


# ---------------------------------------------------------------- entry
def run(fleetctl, args):
    """Called by fleetctl.main for `cost`. fleetctl is the fleetctl module (registry, log, config)."""
    cwd = args.cwd or os.getcwd()
    reg = fleetctl.load_registry(cwd, args.project)
    cfg = fleetctl.project_config(cwd)
    repo = fleetctl.git(cwd, "rev-parse", "--show-toplevel") or cwd
    common = fleetctl.git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    main_repo = os.path.dirname(common.rstrip("/")) if common else repo
    project = args.project or reg.get("_project")
    identifier = (cfg.get("plane") or {}).get("identifier")
    trunk = (cfg.get("git") or {}).get("trunk")
    prices = reg.get("prices") or {}
    cost_cfg = (cfg.get("fleet") or {}).get("cost") or {}
    dirs = project_dirs(main_repo, cost_cfg.get("claude_project_dirs") or (), args.claude_dir)
    cache_dir = os.path.join(fleetctl.STATE_HOME, "cost-cache")
    since = args.since
    if not since and not args.ticket:
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    mains, agents = collect(dirs, cache_dir, identifier)
    rows = fleetctl.load_rows(reg)
    lanes = lane_sessions(rows, project)
    if args.backfill:
        new = backfill_rows(agents, rows, prices, project)
        todo = sum(1 for r in rows if (r.get("executor") or "claude") == "claude" and r.get("role") != "pm"
                   and r.get("type", "spawn") == "spawn" and not r.get("usage_only")
                   and (not project or r.get("project") == project) and not isinstance(r.get("input_tokens"), (int, float)))
        if args.dry_run:
            print(f"would back-fill {len(new)} of {todo} Claude spawn rows of {project} without real usage")
            for r in new[:5]:
                print(f"  {r['ticket']} {r['role']} {r['ts']} agent {r['agent_id']}: {ktok(r['input_tokens'])} in, "
                      f"{ktok(r['output_tokens'])} out, {money(r['usd'])}")
            return 0
        for r in new:
            fleetctl.append_row(reg, r)
        print(f"back-filled real usage onto {len(new)} of {todo} Claude spawn rows of {project}")
        return 0
    day = (since or "")[:10] or None
    prs, err = merged_prs(main_repo, trunk, day)
    proj_rows = [r for r in rows if not project or r.get("project") == project]
    res = analyse(mains, agents, lanes, prs, prices, identifier, since, args.until, proj_rows)
    if args.ticket:
        x = res["tickets"].get(args.ticket)
        if not x:
            print(f"{args.ticket}: no sessions found" + (f" since {since}" if since else ""))
            return 1
        print(json.dumps(_jsonable(x), indent=2) if args.json else render_ticket(x))
        return 0
    if args.json:
        out = {k: v for k, v in res.items() if k not in ("tickets", "merged")}
        out["tickets"] = [_jsonable(x) for x in sorted(res["tickets"].values(), key=lambda x: x["first"])]
        out["project"], out["merge_error"], out["project_dirs"] = project, err, dirs
        print(json.dumps(out, indent=2, default=str))
    else:
        print(render(res, project, prices, err, dirs))
    return 0


def _jsonable(x):
    iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None
    y = dict(x)
    for k in ("first", "merged", "pr_opened"):
        if k in y:
            y[k] = iso(y[k])
    y["sessions"] = [dict(s, start=iso(s["start"]), end=iso(s["end"])) for s in x["sessions"]]
    return y


# ---------------------------------------------------------------- selftest
def selftest(check):
    """Builds a fake Claude projects folder and checks dedupe, pricing, attribution and backfill."""
    import tempfile
    d = tempfile.mkdtemp(prefix="fleetcost-selftest-")
    repo = os.path.join(d, "repo")
    os.makedirs(os.path.join(repo, ".claude", "worktrees", "x"))
    proot = os.path.join(d, "projects")
    pdir = os.path.join(proot, encode_path(repo))
    os.makedirs(os.path.join(pdir, "S1", "subagents"))
    os.makedirs(os.path.join(proot, encode_path(repo) + "-mobile"))          # sibling repo: not ours
    os.makedirs(os.path.join(proot, encode_path(repo) + "--claude-worktrees-x"))  # worktree: ours
    prices = {"source": "test", "cache_write_multiplier": {"5m": 1.25, "1h": 2.0},
              "models": {"claude-opus-5-5": {"input": 4, "output": 20, "cache_read": 0.2}}}

    def line(kind, ts, mid=None, usage=None, content=None, **kw):
        r = {"type": kind, "timestamp": ts, **kw}
        if kind == "assistant":
            r["message"] = {"id": mid, "model": "claude-opus-5-5", "usage": usage, "content": content or []}
        else:
            r["message"] = {"content": content}
        return json.dumps(r) + "\n"
    u1 = {"input_tokens": 10, "cache_creation_input_tokens": 100000, "cache_read_input_tokens": 0, "output_tokens": 1000,
          "cache_creation": {"ephemeral_5m_input_tokens": 100000, "ephemeral_1h_input_tokens": 0}}
    u2 = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100000, "output_tokens": 1000}
    u3 = {"input_tokens": 0, "cache_creation_input_tokens": 101000, "cache_read_input_tokens": 0, "output_tokens": 0,
          "cache_creation": {"ephemeral_5m_input_tokens": 101000, "ephemeral_1h_input_tokens": 0}}
    agent = os.path.join(pdir, "S1", "subagents", "agent-abc.jsonl")
    with open(agent, "w") as f:
        f.write(line("user", "2026-10-01T10:00:00Z", content="Fleet folder: /x. Work ST-7. Slot: A."))
        # one API call written as two lines (two content blocks): counted once
        f.write(line("assistant", "2026-10-01T10:00:05Z", "m1", u1, [{"type": "tool_use", "name": "Bash", "input": {"command": "sed -n 1,20p a.ts"}}]))
        f.write(line("assistant", "2026-10-01T10:00:05Z", "m1", u1, [{"type": "tool_use", "name": "Bash", "input": {"command": "grep -n x a.ts"}}]))
        f.write(line("assistant", "2026-10-01T10:01:00Z", "m2", u2, [{"type": "tool_use", "name": "Edit", "input": {"file_path": "a.ts"}}]))
        # an 8-minute wait, then the whole context is written again
        f.write(line("assistant", "2026-10-01T10:09:00Z", "m3", u3, []))
    json.dump({"agentType": "fleet-engineer", "description": "engineer ST-7", "model": "opus"}, open(agent[:-6] + ".meta.json", "w"))
    with open(os.path.join(pdir, "S1.jsonl"), "w") as f:
        f.write(line("user", "2026-10-01T09:59:00Z", content="run the board with team-pm"))
        f.write(line("assistant", "2026-10-01T09:59:30Z", "p1", u2, [{"type": "tool_use", "name": "Agent", "input": {"subagent_type": "fleet-engineer"}}]))
    dirs = project_dirs(repo, root=proot)
    check("project dirs: repo and worktree, not the sibling", sorted(os.path.basename(x) for x in dirs),
          sorted([encode_path(repo), encode_path(repo) + "--claude-worktrees-x"]))
    cache = os.path.join(d, "cache")
    mains, agents = collect(dirs, cache, "ST")
    a = agents[0]
    check("dedupe by message id", a["calls"], 3)
    check("ticket from description", a["tickets"], ["ST-7"])
    check("role from agent type", a["role"], "engineer")
    want = (10 * 4 + 100000 * 4 * 1.25 + 1000 * 20 + 100000 * 0.2 + 1000 * 20 + 101000 * 4 * 1.25) / 1e6
    check("usd", round(usd_by_model(prices, a["by_model"])[0], 6), round(want, 6))
    check("rewrite after a wait", a["rewrites"]["claude-opus-5-5"][1], 101000)
    check("first-call context", a["first_ctx"], 100010)
    check("PM session found", [m["kind"] for m in mains], ["pm"])
    check("cache hit", collect(dirs, cache, "ST")[1][0]["calls"], 3)
    os.remove(agent)
    os.remove(agent[:-6] + ".meta.json")
    gone = collect(dirs, cache, "ST")[1]
    check("a deleted session stays counted from the cache", [(g["agent_id"], g["tickets"], g["role"]) for g in gone],
          [("abc", ["ST-7"], "engineer")])
    prs = [{"number": 9, "title": "feat: x (ST-7)", "headRefName": "feat/ST-7-x", "createdAt": "2026-10-01T10:05:00Z",
            "mergedAt": "2026-10-01T12:00:00Z", "additions": 100, "deletions": 20, "changedFiles": 3}]
    rows = [{"type": "spawn", "ts": "2026-10-01T10:09:30Z", "project": "st", "ticket": "ST-7", "role": "engineer",
             "executor": "claude", "model": "opus", "outcome": "pr_opened", "tokens": 101000}]
    res = analyse(mains, agents, [], prs, prices, "ST", "2026-10-01T00:00:00Z", None, rows)
    x = res["tickets"]["ST-7"]
    check("cycle hours", round(x["cycle_h"], 2), 2.0)
    check("merged count", len(res["merged"]), 1)
    bf = backfill_rows(agents, rows, prices, "st")
    check("backfill matches the agent", [r["agent_id"] for r in bf], ["abc"])
    check("backfill input counts cache reads", bf[0]["input_tokens"], 10 + 100000 + 100000 + 101000)
    check("text report renders", "Merged tickets: 1" in render(res, "st", prices), True)
    check("ticket view renders", "ST-7" in render_ticket(x), True)
    import shutil
    shutil.rmtree(d, ignore_errors=True)
