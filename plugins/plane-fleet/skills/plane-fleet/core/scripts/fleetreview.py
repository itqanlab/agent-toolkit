#!/usr/bin/env python3
"""fleetreview: the same review of every run, kept, so runs can be compared.

Finds the runs in the outcomes log (a gap of more than `gap_hours` between rows starts a new
run), measures each one with the same code as `fleet cost` and `fleet retro`, keeps one
scorecard per finished run in {state_home}/reviews/<project>.jsonl, and prints the last runs
side by side: spend, time, quality, the PM, the executor mix, the decisions made on the run's
days and the toolkit versions released since the run before.

  fleet review [--cwd REPO] [--project P] [--since ISO] [--last N] [--gap-hours H]
               [--json] [--md FILE] [--no-record] [--rebuild]

A run whose last row is less than `gap_hours` old is open: it is measured and shown, never kept.
Runs with fewer than `min_rows` session rows are left out (a single test spawn is not a run).
Config: `fleet.review` (core/references/config-schema.md).

Exit codes: 0 done, 1 no runs found.
Standard library only. Python 3.9.
"""
import collections, datetime, json, os, re, statistics, time

import fleetcost
import fleetretro

DEFAULTS = {"gap_hours": 4, "min_rows": 5, "compare_runs": 5, "change_pct": 10}
MERGE_DAYS = 7      # a ticket started in a run counts as merged when it merges up to this long after the run
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The three goals count the same. A run is judged on all three at once: a gain on one bought by a
# loss on another is a trade, shown as one, never called an improvement.
GOALS = ("time", "results", "cost")

# key, label, format, which way is better (+1 higher, -1 lower, 0 neither), goal it decides (None = a driver)
METRICS = [
    ("merged_per_hour", "merged tickets per run hour", "f2", 1, "time"),
    ("cycle_median_h", "spawn to merge, median h", "f1", -1, "time"),
    ("cycle_p90_h", "spawn to merge, p90 h", "f1", -1, "time"),
    ("rework_rate", "rework rate", "pct", -1, "results"),
    ("merged_share", "merged of started", "pct", 1, "results"),
    ("escapes", "escapes logged", "n", -1, "results"),
    ("usd_per_merged", "$ per merged ticket", "usd", -1, "cost"),
    ("merged", "merged tickets", "n", 0, None),
    ("spend_usd", "spend", "usd", 0, None),
    ("lanes_usd", "  of it lanes", "usd", 0, None),
    ("pm_usd", "  of it PM", "usd", 0, None),
    ("codex_points", "Codex meter points", "f1", -1, None),
    ("active_median_h", "agents working, median h", "f1", 0, None),
    ("fleet_running", "fleet running share", "pct", 1, None),
    ("merge_wait_avg_h", "pass to merge, avg h", "f1", -1, None),
    ("lost_h", "lost to sleep or login, h", "f1", -1, None),
    ("sessions_per_merged", "sessions per merged ticket", "f1", -1, None),
    ("pm_ctx_k", "PM context per call, k", "n", -1, None),
    ("pm_calls_per_merged", "PM calls per merged ticket", "f1", -1, None),
    ("pm_share", "PM share of spend", "pct", -1, None),
    ("lane_failures", "lane failures", "n", -1, None),
    ("unknown_cost_sessions", "sessions with no usage", "n", -1, None),
]


def settings(cfg):
    out = dict(DEFAULTS)
    out.update(((cfg.get("fleet") or {}).get("review") or {}))
    return out


def iso(t):
    return fleetretro.iso(t)


def epoch(s):
    return fleetcost.epoch(s)


# ---------------------------------------------------------------- runs
def find_runs(rows, project, gap_h, min_rows, since=None):
    """[(t0, t1, n_rows)] from the log's session rows. t0 backs off the first row's duration,
    since a row is written when its session ends."""
    pts = []
    for r in rows:
        if r.get("type", "spawn") != "spawn" or r.get("usage_only") or (project and r.get("project") != project):
            continue
        t = epoch(r.get("ts"))
        if not t or (since and t < since):
            continue
        dur = r.get("duration_ms") if isinstance(r.get("duration_ms"), (int, float)) else 0
        pts.append((t, t - dur / 1000))
    pts.sort()
    runs, cur = [], None
    for t, start in pts:
        if cur and t - cur[1] <= gap_h * 3600:
            cur[1] = t
            cur[0] = min(cur[0], start)
            cur[2] += 1
        else:
            if cur:
                runs.append(cur)
            cur = [start, t, 1]
    if cur:
        runs.append(cur)
    # ten minutes past the last row, so its own bucket is inside the window
    return [(int(a // 600) * 600, int(b // 600) * 600 + 600, n) for a, b, n in runs if n >= min_rows]


def changelog_versions(path=None):
    """[(date, version)] from the skill's CHANGELOG, oldest first."""
    path = path or os.path.join(FLEET_ROOT, "CHANGELOG.md")
    out = []
    try:
        for line in open(path):
            m = re.match(r"## \[([^\]]+)\] - (\d{4}-\d{2}-\d{2})", line)
            if m:
                out.append((m.group(2), m.group(1)))
    except OSError:
        pass
    return sorted(out)


def version_at(versions, day):
    v = [ver for d, ver in versions if d <= day]
    return v[-1] if v else None


def decisions_on(path, day0, day1):
    """Lines of executor-decisions.md dated on the run's days (day granularity)."""
    out = []
    try:
        for line in open(path):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
            if m and day0 <= m.group(1) <= day1 and len(line.strip()) > 12:
                out.append(re.sub(r"\s+", " ", line.strip().strip("-|# ")).strip()[:240])
    except OSError:
        pass
    return out


def day(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d")


STAGES = ("build", "wait_engineer", "wait_test", "test", "wait_rework", "rework", "to_merge", "fleet_off")
WORK_ROLES = ("engineer", "rework", "tester", "retest")


def work_sessions(x):
    """The sessions that are work on the ticket. A reviewer that only names the ticket in its brief,
    or a group merge, is not: counting one moved a ticket's start 13 days early (2026-11-16)."""
    return sorted((s for s in x.get("sessions") or [] if s.get("role") in WORK_ROLES and s.get("start") is not None
                   and not str(s.get("description") or "").lower().startswith("merge")), key=lambda s: s["start"])


def alive_buckets(mains, agents, lanes):
    """10-minute buckets in which any PM session, agent or lane of the project was running."""
    B = fleetcost.BUCKET_S
    alive = set()
    for m in mains:
        if m.get("kind") == "pm":
            alive.update(int(b) for b in m.get("buckets") or ())
    for a in agents:
        alive.update(int(b) for b in a.get("buckets") or ())
    for l in lanes:
        if l.get("start") and l.get("end"):
            alive.update(range(int(l["start"] // B), int(l["end"] // B) + 1))
    return alive


def split_alive(a, b, alive):
    """Seconds of [a, b) with the fleet running, and with it stopped."""
    if alive is None:
        return b - a, 0.0
    B = fleetcost.BUCKET_S
    on = 0.0
    k = int(a // B)
    while k * B < b:
        lo, hi = max(a, k * B), min(b, (k + 1) * B)
        if hi > lo and k in alive:
            on += hi - lo
        k += 1
    return on, (b - a) - on


def time_stages(x, alive=None):
    """A merged ticket's first work to merge, cut into stages, in hours. The first engineer work is
    the build, engineer work after the first test is rework; a gap before a session is waiting for
    that kind of session, the gap after the last one is waiting to merge. Gap time with no fleet
    session running anywhere is `fleet_off`. Overlapping sessions count once."""
    out = dict.fromkeys(STAGES, 0.0)
    merged = x.get("merged")
    ss = work_sessions(x)
    if merged is None or not ss or ss[0]["start"] >= merged:
        return None

    def wait(kind, a, b):
        on, off = split_alive(a, b, alive)
        out[kind] += on
        out["fleet_off"] += off

    cursor, tested = ss[0]["start"], False
    for s in ss:
        if s["start"] >= merged:
            break
        test = s.get("role") in ("tester", "retest")
        kind = "test" if test else "rework" if (s.get("role") == "rework" or tested) else "build"
        if s["start"] > cursor:
            wait("wait_" + ("test" if test else "rework" if kind == "rework" else "engineer"), cursor, s["start"])
        a, b = max(s["start"], cursor), min(s.get("end") or s["start"], merged)
        if b > a:
            out[kind] += b - a
        cursor = max(cursor, b)
        tested = tested or test
    if merged > cursor:
        wait("to_merge", cursor, merged)
    return {k: v / 3600 for k, v in out.items()}


def timelines(tickets, rows, project, alive):
    """Per ticket, over all its sessions (not only one run's): first work, merge, cycle, stages,
    rework rounds (test failures before the merge), last pass to merge, cost."""
    fails, passes = {}, {}
    for r in rows:
        if r.get("type", "spawn") != "spawn" or (project and r.get("project") != project) or not r.get("ticket"):
            continue
        t = epoch(r.get("ts"))
        if r.get("outcome") == "verify_fail":
            fails.setdefault(r["ticket"], []).append(t)
        elif r.get("outcome") == "verify_pass":
            passes.setdefault(r["ticket"], []).append(t)
    out = {}
    for t, x in tickets.items():
        ws = work_sessions(x)
        if not ws:
            continue
        first, merged = ws[0]["start"], x.get("merged")
        y = {"ticket": t, "first": first, "merged": None, "cost": x.get("cost") or 0}
        if merged and merged > first:
            iv, active = sorted((s["start"], min(s.get("end") or s["start"], merged)) for s in ws if s["start"] < merged), 0.0
            end = None
            for a, b in iv:
                a = max(a, end or a)
                if b > a:
                    active += b - a
                end = max(end or b, b)
            ps = [p for p in passes.get(t, []) if first <= p <= merged]
            y.update(merged=merged, cycle_h=(merged - first) / 3600, active_h=active / 3600,
                     stages=time_stages(x, alive), rounds=sum(1 for f in fails.get(t, []) if first <= f <= merged),
                     pass_to_merge_h=((merged - max(ps)) / 3600) if ps else None)
        out[t] = y
    return out


def rework_groups(merged):
    """Cycle median and $ mean for merged tickets with 0, 1 and 2+ rework rounds."""
    out = {}
    for name, sel in (("0", lambda n: n == 0), ("1", lambda n: n == 1), ("2+", lambda n: n >= 2)):
        g = [x for x in merged if sel(x["rounds"])]
        if g:
            out[name] = {"n": len(g), "cycle_median_h": statistics.median(x["cycle_h"] for x in g),
                         "usd_mean": sum(x["cost"] for x in g) / len(g)}
    return out


def scorecard(d, tl, alive, t0, t1, n_rows, rows, project, versions, decisions_path):
    """d: the retro's numbers for the run window. tl: the tickets whose first work was in this run,
    with their whole timelines, so a ticket is counted in one run only."""
    merged = [x for x in tl if x["merged"]]
    n = len(merged)
    started = len(tl)
    s = d["spend"]
    spend = (s["pm"] or 0) + (s["agents"] or 0)
    q = fleetcost.quantiles([x["cycle_h"] for x in merged]) or {}
    qa = fleetcost.quantiles([x["active_h"] for x in merged]) or {}
    wait = [x["pass_to_merge_h"] for x in merged if x["pass_to_merge_h"] is not None]
    on = sum(split_alive(x["first"], x["merged"], alive)[0] for x in merged)
    cyc = sum(x["merged"] - x["first"] for x in merged)
    lost = d.get("lost")
    win = [r for r in rows if r.get("type", "spawn") == "spawn" and not r.get("usage_only")
           and (not project or r.get("project") == project) and t0 <= (epoch(r.get("ts")) or 0) < t1]
    sess = [r for r in win if r.get("outcome") not in ("retro_fix", "decision") and r.get("role") != "pm"]
    mix = {}
    for r in sess:
        k = f"{r.get('role')} {r.get('executor') or 'claude'}:{r.get('model') or '?'}"
        mix[k] = mix.get(k, 0) + 1
    blocked = [r for r in sess if r.get("outcome") == "blocked"]
    cr = d["codex"]["pts_per_hour"]
    no_usage = sum((s.get("lanes_no_usage") or {}).values())
    st = [x["stages"] for x in merged if x.get("stages")]
    stages_h = {k: sum(y[k] for y in st) for k in STAGES} if st else None
    return {
        "project": project, "start": iso(t0), "end": iso(t1), "hours": round((t1 - t0) / 3600, 1), "rows": n_rows,
        "version": version_at(versions, day(t0)),
        "changes_since_prev": [],
        "started": started, "merged": n, "merged_share": (n / started) if started else None,
        "merged_per_hour": (n / ((t1 - t0) / 3600)) if t1 > t0 else None,
        # only as good as the logging: bug_filed, reverted and review escapes written onto the rows
        "escapes": sum(1 for r in win if r.get("bug_filed") or r.get("reverted") is True
                       or "review escape" in str(r.get("reason") or "")),
        "spend_usd": spend, "pm_usd": s["pm"], "claude_agents_usd": s.get("claude_agents"), "lanes_usd": s.get("lanes"),
        "usd_per_merged": (spend / n) if n else None,
        "unpriced_tokens": dict(s.get("lanes_unpriced") or {}), "unknown_cost_sessions": no_usage,
        "codex_points": (cr * d["hours"]) if cr is not None else None,
        "cycle_median_h": q.get("median"), "cycle_p90_h": q.get("p90"), "active_median_h": qa.get("median"),
        "fleet_running": (on / cyc) if cyc else None,
        "merge_wait_avg_h": (sum(wait) / len(wait)) if wait else None,
        "lost_h": (sum(lost.values())) if lost is not None else None,
        "rework_rate": d["rework"]["rate"], "fail_causes": d["rework"]["causes"],
        "sessions_per_merged": (len(sess) / n) if n else None,
        "pm_ctx_k": (d["pm"]["ctx_per_call"] / 1000) if d["pm"].get("ctx_per_call") else None,
        "pm_calls_per_merged": (d["pm"]["calls"] / n) if (n and d["pm"].get("calls")) else None,
        "pm_share": s["pm_share"],
        "lane_failures": max(len(d["lanes"]["failed"]), d["lanes"]["log_failed"]),
        "stages_h": stages_h,
        "by_rework": rework_groups(merged),
        "rework_rate_merged": (sum(1 for x in merged if x["rounds"]) / n) if n else None,
        "mix": dict(sorted(mix.items(), key=lambda kv: -kv[1])),
        "blocked": len(blocked), "blocked_no_reason": sum(1 for r in blocked if not r.get("reason")),
        "defects": dict(collections.Counter(r.get("defect") or "not logged" for r in sess
                                            if r.get("outcome") == "verify_fail" and r.get("fail_cause") == "missed")),
        "fails_no_reason": sum(1 for r in sess if r.get("outcome") == "verify_fail" and not r.get("reason")),
        "retro_fixes": [x.get("reason") for x in d["retro_fixes"]],
        # logged decision rows carry their time; the decisions file only its day
        "decisions": [f"{x['ts'][5:16].replace('T', ' ')} {x.get('reason')}" for x in d.get("decisions") or []]
        + decisions_on(decisions_path, day(t0), day(t1 - 1)),
        "findings": {f["key"]: f["level"] for f in d.get("findings") or []},
        "measured_at": iso(time.time()),
    }


# ---------------------------------------------------------------- history
def history_path(state_home, project):
    return os.path.join(state_home, "reviews", f"{project}.jsonl")


def read_history(path):
    out = {}
    try:
        for line in open(path):
            try:
                c = json.loads(line)
            except ValueError:
                continue
            out[c["start"]] = c          # a later line for the same run wins
    except OSError:
        pass
    return [out[k] for k in sorted(out)]


def append_history(path, cards):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        for c in cards:
            f.write(json.dumps(c, default=str) + "\n")


def link_changes(cards, versions):
    """Each run names the toolkit versions released after the run before it started."""
    prev = None
    for c in cards:
        if prev:
            c["changes_since_prev"] = [v for d, v in versions if day(epoch(prev["start"])) < d <= day(epoch(c["start"]))]
        prev = c
    return cards


# ---------------------------------------------------------------- compare
def fmt(v, kind):
    if v is None:
        return "—"
    if kind == "usd":
        return fleetcost.money(v)
    if kind == "pct":
        return f"{100 * v:.0f}%"
    if kind == "f1":
        return f"{v:.1f}"
    if kind == "f2":
        return f"{v:.2f}"
    return f"{v:.0f}"


def verdicts(cur, before, change_pct):
    """Metrics that moved by more than change_pct against the median of the runs before."""
    out = []
    for key, label, kind, better, goal in METRICS:
        if better == 0 or cur.get(key) is None:
            continue
        past = [c.get(key) for c in before if c.get(key) is not None]
        if not past:
            continue
        ref = statistics.median(past)
        if ref == 0:
            moved = cur[key] != 0
            rel = None
        else:
            rel = (cur[key] - ref) / abs(ref)
            moved = abs(rel) * 100 > change_pct
        if moved:
            good = (cur[key] - ref) * better > 0
            out.append({"key": key, "label": label.strip(), "goal": goal, "now": cur[key], "ref": ref, "rel": rel,
                        "better": good, "shown": f"{fmt(cur[key], kind)} vs {fmt(ref, kind)}"})
    return out


def goal_verdicts(verdict):
    """Per goal: better, worse, mixed or same, from its headline metrics; and the run overall."""
    out = {}
    for g in GOALS:
        moved = [v for v in verdict or [] if v.get("goal") == g]
        up, down = any(v["better"] for v in moved), any(not v["better"] for v in moved)
        out[g] = {"verdict": "mixed" if (up and down) else "better" if up else "worse" if down else "same",
                  "moved": moved}
    vs = [out[g]["verdict"] for g in GOALS]
    if any(v in ("worse", "mixed") for v in vs) and any(v in ("better", "mixed") for v in vs):
        overall = "trade: one goal gained what another lost, so not an improvement"
    elif any(v == "better" for v in vs):
        overall = "gain: better on at least one goal, worse on none"
    elif any(v == "worse" for v in vs):
        overall = "loss: worse on at least one goal, better on none"
    else:
        overall = "no change on any goal"
    return out, overall


def goal_lines(verdict):
    gv, overall = goal_verdicts(verdict)
    L = [f"  overall: {overall}"]
    for g in GOALS:
        m = gv[g]["moved"]
        L.append(f"  {g + ':':<9}{gv[g]['verdict']:<8}" + (" · ".join(
            f"{v['label']} {v['shown']} ({'better' if v['better'] else 'worse'})" for v in m) if m else "nothing moved"))
    return L


STAGE_LABELS = {"build": "building", "wait_engineer": "waiting for an engineer", "wait_test": "waiting for a tester",
                "test": "testing", "wait_rework": "waiting for rework", "rework": "rework", "to_merge": "pass to merge",
                "fleet_off": "waiting while no fleet session ran"}


def stage_lines(card, pad):
    sh = card.get("stages_h")
    L = []
    if sh and sum(sh.values()):
        tot = sum(sh.values())
        L.append(pad + "where merged tickets' time went: " + " · ".join(
            f"{STAGE_LABELS[k]} {100 * v / tot:.0f}%" for k, v in sorted(sh.items(), key=lambda kv: -kv[1]) if v / tot >= 0.01))
    br = card.get("by_rework") or {}
    if br:
        L.append(pad + "by rework rounds: " + " · ".join(
            f"{k}: {g['n']} tickets, {g['cycle_median_h']:.1f}h median, {fleetcost.money(g['usd_mean'])} mean" for k, g in br.items()))
    return L


def render(cards, open_card, verdict, project, notes):
    L = [f"Fleet review · {project} · {len(cards)} run(s) kept" + (" + 1 open" if open_card else "")]
    for n in notes:
        L.append(f"  {n}")
    cols = cards + ([open_card] if open_card else [])
    if not cols:
        return "\n".join(L + ["", "No runs found."])
    head = [c["start"][5:16].replace("T", " ") + ("*" if c is open_card else "") for c in cols]
    w = max(12, max(len(h) for h in head) + 1)
    L.append("")
    L.append(f"  {'run start (UTC)':<28}" + "".join(f"{h:>{w}}" for h in head))
    L.append(f"  {'hours':<28}" + "".join(f"{c['hours']:>{w}.1f}" for c in cols))
    L.append(f"  {'toolkit version':<28}" + "".join(f"{(c.get('version') or '—'):>{w}}" for c in cols))
    for g in GOALS + (None,):
        L.append(f"  {('-- ' + g) if g else '-- drivers':<28}")
        for key, label, kind, _, goal in METRICS:
            if goal == g:
                L.append(f"  {label:<28}" + "".join(f"{fmt(c.get(key), kind):>{w}}" for c in cols))
    if open_card:
        L.append("  * open: the run is still going, so it is not kept and not judged")
    last = cards[-1] if cards else None
    if last:
        L.append("")
        L.append(f"Last finished run, {last['start'][:16].replace('T', ' ')} to {last['end'][11:16]} UTC")
        if verdict is None:
            L.append("  first run kept: nothing to compare with yet")
        else:
            L.append("  against the median of the runs before; time, results and cost count the same")
            L += goal_lines(verdict)
            drv = [v for v in verdict if v.get("goal") is None]
            if drv:
                L.append("  drivers that moved: " + ", ".join(
                    f"{v['label']} {v['shown']} ({'better' if v['better'] else 'worse'})" for v in drv))
        if last.get("changes_since_prev"):
            L.append("  toolkit versions since the run before: " + ", ".join(last["changes_since_prev"]))
        L += stage_lines(last, "  ")
        top = list(last["mix"].items())[:6]
        if top:
            L.append("  sessions: " + ", ".join(f"{k} {v}" for k, v in top))
        if last.get("blocked"):
            L.append(f"  blocked sessions: {last['blocked']}, {last['blocked_no_reason']} with no reason logged")
        for x in last.get("decisions") or []:
            L.append(f"  decision: {x}")
        for x in last.get("retro_fixes") or []:
            L.append(f"  retro fix: {x}")
        if last.get("fail_causes"):
            L.append("  test failures by cause: " + ", ".join(f"{k} {v}" for k, v in sorted(last["fail_causes"].items(), key=lambda kv: -kv[1])))
        if last.get("defects"):
            L.append("  missed defects by class: " + ", ".join(f"{k} {v}" for k, v in sorted(last["defects"].items(), key=lambda kv: -kv[1])))
        if last.get("fails_no_reason"):
            L.append(f"  test failures with no reason logged: {last['fails_no_reason']}")
        al = [k for k, lv in (last.get("findings") or {}).items() if lv == "alert"]
        if al:
            L.append("  retro alerts: " + ", ".join(al))
        if last.get("unknown_cost_sessions"):
            L.append(f"  {last['unknown_cost_sessions']} lane session(s) logged no usage: their cost is unknown, not zero")
        if last.get("unpriced_tokens"):
            L.append("  no price, not in spend: " + ", ".join(f"{k} {fleetcost.ktok(v)}" for k, v in last["unpriced_tokens"].items()))
    return "\n".join(L)


def render_md(cards, open_card, verdict, project, notes):
    """The same review as markdown, for the record board."""
    cols = cards[-5:]
    L = [f"# Fleet review: {project}, run of {cols[-1]['start'][:10] if cols else '?'}", ""]
    for n in notes:
        L.append(f"- {n}")
    if cols:
        L.append("")
        L.append("| metric | " + " | ".join(c["start"][5:16].replace("T", " ") for c in cols) + " |")
        L.append("|---|" + "---|" * len(cols))
        L.append("| toolkit version | " + " | ".join(c.get("version") or "—" for c in cols) + " |")
        for key, label, kind, _, goal in sorted(METRICS, key=lambda m: (GOALS + (None,)).index(m[4])):
            L.append(f"| {(goal + ': ') if goal else ''}{label.strip()} | " + " | ".join(fmt(c.get(key), kind) for c in cols) + " |")
        last = cols[-1]
        L.append("")
        if verdict:
            L.append("## Against the runs before (median)")
            L.append("")
            L.append("Time, results and cost count the same.")
            L.append("")
            L += ["- " + x.strip() for x in goal_lines(verdict)]
            L.append("")
        sl = stage_lines(last, "- ")
        if sl:
            L.append("## Where the time went")
            L.append("")
            L += sl
            L.append("")
        L.append("## What was decided and changed")
        L.append("")
        for x in last.get("changes_since_prev") or []:
            L.append(f"- toolkit {x}")
        for x in last.get("decisions") or []:
            L.append(f"- decision: {x}")
        for x in last.get("retro_fixes") or []:
            L.append(f"- retro fix: {x}")
        if not (last.get("changes_since_prev") or last.get("decisions") or last.get("retro_fixes")):
            L.append("- nothing logged")
        L.append("")
        L.append("## What we change before the next run")
        L.append("")
        L.append("- (fill in: one line per change, with the metric it should move)")
    if open_card:
        L.append("")
        L.append(f"A run is still open since {open_card['start'][:16].replace('T', ' ')} UTC; it is not in this review.")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- command
def run(fleetctl, args):
    cwd = args.cwd or os.getcwd()
    now = time.time()
    ctx0 = {"cfg": fleetctl.project_config(cwd)}
    st = settings(ctx0["cfg"])
    gap = args.gap_hours or st["gap_hours"]
    reg = fleetctl.load_registry(cwd, args.project)
    project = args.project or reg.get("_project")
    hpath = history_path(fleetctl.STATE_HOME, project)
    kept = [] if args.rebuild else read_history(hpath)
    since = epoch(args.since) if args.since else None
    if args.since and since is None:
        raise SystemExit(f"fleet review: --since {args.since!r} is not an ISO time")
    if since is None:
        since = epoch(kept[-1]["end"]) if kept else now - 30 * 86400
    rows = fleetctl.load_rows(reg)
    runs = find_runs(rows, project, gap, st["min_rows"], since)
    done = {c["start"] for c in kept}
    todo = [(a, b, n) for a, b, n in runs if iso(a) not in done or args.rebuild]
    notes = []
    versions = changelog_versions()
    decisions_path = os.path.join(fleetctl.STATE_HOME, "executor-decisions.md")
    new_cards, open_card, failed = [], None, 0
    if todo:
        ctx = fleetretro.load(fleetctl, cwd, project, args.claude_dir, iso(todo[0][0]), prs=False)
        alive = alive_buckets(ctx["mains"], ctx["agents"], ctx["lane_rows"])
        th, lv = fleetretro.thresholds(ctx["cfg"])
        for a, b, n in todo:
            is_open = now - b < gap * 3600
            t1 = min(b, now) if not is_open else now
            # merges per run: one call for months hits gh's 1000 cap, and a ticket can merge days after its run
            prs, perr = fleetcost.merged_prs(ctx["main_repo"], (ctx["cfg"].get("git") or {}).get("trunk"),
                                             day(a), day(t1 + MERGE_DAYS * 86400))
            if prs is None or perr:
                failed += 1
                notes.append(f"run {iso(a)[:16]}: merges not read ({perr}); not kept")
                continue
            ctx["prs"] = prs
            d, _ = fleetretro.measure(fleetctl, ctx, a, t1, now, until_given=not is_open)
            d["findings"] = fleetretro.evaluate(d, th, lv)
            every = fleetcost.build_tickets(ctx["agents"], ctx["lane_rows"], prs, ctx["prices"], ctx["identifier"],
                                            None, None, ctx["proj_rows"])
            tl = [y for y in timelines(every, ctx["proj_rows"], project, alive).values() if a <= y["first"] < t1]
            card = scorecard(d, tl, alive, a, t1, n, rows, project, versions, decisions_path)
            if is_open:
                open_card = card
            else:
                new_cards.append(card)
    cards = link_changes(sorted(([] if args.rebuild else kept) + new_cards, key=lambda c: c["start"]), versions)
    if new_cards and not args.no_record:
        if args.rebuild and failed:
            notes.append(f"--rebuild kept nothing: {failed} run(s) had no merge data, and a partial rebuild would lose them")
        elif args.rebuild:
            os.makedirs(os.path.dirname(hpath), exist_ok=True)
            open(hpath, "w").close()
            append_history(hpath, cards)
        else:
            append_history(hpath, [c for c in cards if c["start"] in {x["start"] for x in new_cards}])
        notes.append(f"kept {len(new_cards)} new run(s) in {hpath}")
    elif new_cards:
        notes.append("--no-record: nothing kept")
    shown = cards[-(args.last or st["compare_runs"]):]
    verdict = verdicts(cards[-1], cards[-1 - st["compare_runs"]:-1], st["change_pct"]) if len(cards) >= 2 else None
    notes.append("prices are API list prices, to compare runs; plans bill differently. Lane figures are a floor (see executors.md).")
    if args.md:
        with open(args.md, "w") as f:
            f.write(render_md(shown, open_card, verdict, project, notes))
        notes.append(f"markdown written to {args.md}")
    if args.json:
        print(json.dumps({"project": project, "runs": shown, "open": open_card, "verdict": verdict, "notes": notes},
                         indent=2, default=str))
    else:
        print(render(shown, open_card, verdict, project, notes))
    return 0 if (cards or open_card) else 1


# ---------------------------------------------------------------- selftest
def selftest(check):
    t = 1_790_000_000
    ts = lambda h: iso(t + h * 3600)
    rows = [{"type": "spawn", "project": "st", "ts": ts(h), "duration_ms": 600000} for h in (0, 1, 2, 3, 3.5)]
    rows += [{"type": "spawn", "project": "st", "ts": ts(h)} for h in (10, 11, 12, 13, 14)]
    rows += [{"type": "spawn", "project": "st", "ts": ts(30)}]
    rows += [{"type": "spawn", "project": "other", "ts": ts(h)} for h in (40, 41, 42, 43, 44)]
    runs = find_runs(rows, "st", 4, 5)
    check("review: two runs split on a gap over 4h, a one-row run left out", len(runs), 2)
    check("review: a run starts before its first row by that row's duration", runs[0][0] <= t - 600, True)
    check("review: rows counted per run", [n for _, _, n in runs], [5, 5])
    vs = [("2026-11-01", "2.9.0"), ("2026-11-05", "2.10.0"), ("2026-11-09", "2.11.0")]
    check("review: version at a day", (version_at(vs, "2026-11-06"), version_at(vs, "2026-10-01")), ("2.10.0", None))
    cards = link_changes([{"start": "2026-11-02T00:00:00Z"}, {"start": "2026-11-10T00:00:00Z"}], vs)
    check("review: versions released between two runs", cards[1]["changes_since_prev"], ["2.10.0", "2.11.0"])
    before = [{"usd_per_merged": 20.0, "rework_rate": 0.5}, {"usd_per_merged": 22.0, "rework_rate": 0.6}]
    v = {x["key"]: x for x in verdicts({"usd_per_merged": 10.0, "rework_rate": 0.56}, before, 10)}
    check("review: cheaper is better", (v["usd_per_merged"]["better"], "rework_rate" in v), (True, False))
    v = {x["key"]: x for x in verdicts({"usd_per_merged": 30.0}, before, 10)}
    check("review: dearer is worse", v["usd_per_merged"]["better"], False)
    before = [{"cycle_median_h": 7.0, "usd_per_merged": 19.0, "rework_rate": 0.6}] * 3
    gv, overall = goal_verdicts(verdicts({"cycle_median_h": 3.8, "usd_per_merged": 24.4, "rework_rate": 0.62}, before, 10))
    check("review: faster but dearer is a trade, not a gain", (gv["time"]["verdict"], gv["cost"]["verdict"],
          gv["results"]["verdict"], overall.split(":")[0]), ("better", "worse", "same", "trade"))
    gv, overall = goal_verdicts(verdicts({"cycle_median_h": 3.8, "usd_per_merged": 19.0, "rework_rate": 0.6}, before, 10))
    check("review: faster at the same cost and results is a gain", overall.split(":")[0], "gain")
    h = 3600
    x = {"merged": 10 * h, "sessions": [{"role": "engineer", "start": 0, "end": 2 * h}, {"role": "tester", "start": 3 * h, "end": 4 * h},
                                        {"role": "engineer", "start": 5 * h, "end": 6 * h}, {"role": "retest", "start": 6 * h, "end": 7 * h}]}
    check("review: time stages of one ticket", time_stages(x), {"build": 2.0, "wait_engineer": 0.0, "wait_test": 1.0, "test": 2.0,
                                                                 "wait_rework": 1.0, "rework": 1.0, "to_merge": 3.0,
                                                                 "fleet_off": 0.0})
    alive = set(range(0, 6))           # the fleet ran for the first hour only (six 10-minute buckets)
    check("review: a wait with no fleet running is fleet_off", round(time_stages(x, alive)["fleet_off"], 2), 5.0)
    y = dict(x, sessions=[{"role": "other", "start": -400 * h, "end": -399 * h, "description": "review PR 1 round 12"}]
             + x["sessions"] + [{"role": "engineer", "start": 7 * h, "end": 8 * h, "description": "merge group 3"}])
    check("review: a reviewer naming the ticket and a group merge are not its work", time_stages(y)["build"], 2.0)
    rows = [{"type": "spawn", "project": "st", "ticket": "ST-9", "outcome": "verify_fail", "ts": iso(3 * h)},
            {"type": "spawn", "project": "st", "ticket": "ST-9", "outcome": "verify_pass", "ts": iso(7 * h)}]
    tl = timelines({"ST-9": dict(y, cost=12.0)}, rows, "st", None)["ST-9"]
    check("review: timeline from first work, rounds before the merge",
          (tl["first"], round(tl["cycle_h"], 1), tl["rounds"], round(tl["pass_to_merge_h"], 1)), (0, 10.0, 1, 3.0))
    import tempfile
    p = os.path.join(tempfile.mkdtemp(prefix="fleetreview-selftest-"), "reviews", "st.jsonl")
    append_history(p, [{"start": "a", "x": 1}, {"start": "b", "x": 1}])
    append_history(p, [{"start": "a", "x": 2}])
    check("review: a run kept twice keeps the later card", [c["x"] for c in read_history(p)], [2, 1])
    dp = os.path.join(os.path.dirname(p), "decisions.md")
    with open(dp, "w") as f:
        f.write("| 2026-11-13 | engineer/* | claude:sonnet → codex | owner order | x |\n- 2026-11-01: old line\n")
    check("review: decisions on the run's days", len(decisions_on(dp, "2026-11-13", "2026-11-14")), 1)
