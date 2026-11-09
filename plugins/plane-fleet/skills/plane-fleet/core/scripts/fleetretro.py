#!/usr/bin/env python3
"""fleetretro: the fleet reviews itself.

Reads the outcomes log (the same rows `fleet stats` and `fleet report` read) and the real spend
from the session files (`fleet cost`, fleetcost.py), and says per ticket how many rounds it
took, what it cost, how many tool calls and hours it used, and how it ended. Then it checks
the run against thresholds and prints FINDINGS: the number, the limit, the likely cause, a
concrete fix, and who applies it.

  fleet retro [--since ISO | --hours N] [--until ISO] [--cwd REPO] [--project P] [--json] [--no-record]

Who applies a fix:
  pm       the PM applies it now, inside its routine (briefs, picks, slot use, compaction)
  toolkit  a change to the fleet skill itself; the PM proposes it to the owner with the evidence
  owner    the owner's call (budget, launch flags, a client question)

Thresholds and levels come from config `fleet.retro` (core/references/config-schema.md).
A finding seen in the previous run too (20 minutes to 3 hours earlier) is marked REPEAT; the
PM escalates those. Runs are kept in {state_home}/retro/<project>.json unless --no-record.

Exit codes: 0 healthy (no finding at alert level), 3 a finding at alert level.
Standard library only. Python 3.9.
"""
import datetime, glob, json, os, re, sys, time

import fleetcost

DEFAULTS = {
    "tool_calls_per_session": 300,     # one agent session's tool calls
    "usd_per_ticket": 15,              # a ticket's agent spend in the window, USD
    "pm_share": 0.45,                  # PM spend as a share of PM + agents
    "pm_ctx_per_call": 150000,         # PM context per call, tokens
    "rework_rounds": 2,                # rework rounds on one ticket
    "rework_rate": 0.4,                # tested tickets that went to rework at least once
    "ticket_cause_failures": 0,        # verify_fail rows with cause "ticket" (any is a ticket-writing gap)
    "duplicate_rows": 0,               # the same log row written twice
    "missing_agent_id": 0,             # Claude engineer and tester rows with no agent_id
    "lane_failures": 1,                # lanes that ended failed, timed out or aborted
    "rewrite_share": 0.10,             # agent spend on whole-context cache rewrites after a long wait
    "lane_minutes": 75,                # one lane's run time
    "codex_pts_per_hour": 4.0,         # Codex weekly meter points used per hour, when readable
    "lost_hours": 0.25,                # hours the machine slept or the agents could not run (fleet guard)
}
LEVELS = {
    "tool_calls_per_session": "alert", "usd_per_ticket": "alert", "pm_share": "alert",
    "pm_ctx_per_call": "alert", "rework_rounds": "alert", "rework_rate": "warn",
    "ticket_cause_failures": "alert", "duplicate_rows": "warn", "missing_agent_id": "warn",
    "lane_failures": "warn", "rewrite_share": "warn", "lane_minutes": "warn", "codex_pts_per_hour": "alert",
    "lost_hours": "alert",
}
REPEAT_MIN_S, REPEAT_MAX_S = 20 * 60, 3 * 3600
FAIL_LANE = ("timeout", "failed", "error", "aborted", "killed")


# ---------------------------------------------------------------- helpers
def epoch(s):
    return fleetcost.epoch(s)


def iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def local(t):
    return datetime.datetime.fromtimestamp(t).astimezone().strftime("%m-%d %H:%M") if t else "?"


def money(x):
    return fleetcost.money(x)


def pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def ktok(n):
    return fleetcost.ktok(n)


def thresholds(cfg):
    """DEFAULTS merged with config fleet.retro; levels from fleet.retro.levels ('alert', 'warn', 'off')."""
    r = ((cfg or {}).get("fleet") or {}).get("retro") or {}
    th = dict(DEFAULTS)
    th.update({k: v for k, v in r.items() if k in DEFAULTS and isinstance(v, (int, float))})
    lv = dict(LEVELS)
    lv.update({k: v for k, v in (r.get("levels") or {}).items() if k in LEVELS and v in ("alert", "warn", "off")})
    return th, lv


def tool_calls(agent):
    """Tool calls in one agent session, from fleetcost's activity counts ('text' = a call with no tool)."""
    return int(sum(v[5] for cl, bm in (agent.get("activity") or {}).items() if cl != "text" for v in bm.values()))


def codex_samples(sessions_dir, t0, t1):
    """(ts, used %, resets_at) of Codex's longest rate window, from session logs touched since t0."""
    out = []
    root = os.path.expanduser(sessions_dir or "~/.codex/sessions")
    for path in glob.glob(os.path.join(root, "*", "*", "*", "*.jsonl")):
        try:
            if os.path.getmtime(path) < t0:
                continue
            with open(path, errors="replace") as f:
                for line in f:
                    if '"rate_limits"' not in line:
                        continue
                    try:
                        r = json.loads(line)
                        rl = (r.get("payload") or {}).get("rate_limits") or {}
                    except ValueError:
                        continue
                    t = epoch(r.get("timestamp"))
                    if not t or t < t0 or t >= t1:
                        continue
                    wins = [w for w in (rl.get("primary"), rl.get("secondary")) if w and w.get("used_percent") is not None]
                    if wins:
                        w = max(wins, key=lambda w: w.get("window_minutes") or 0)
                        out.append((t, float(w["used_percent"]), int(w.get("resets_at") or 0)))
        except OSError:
            continue
    return sorted(out)


def codex_rate(samples, hours):
    """Points used per hour over the window: the rise inside each meter window, summed."""
    if len(samples) < 2 or not hours:
        return None
    by_reset = {}
    for t, used, resets in samples:
        by_reset.setdefault(resets, []).append(used)
    rise = sum(max(v) - min(v) for v in by_reset.values())
    return rise / hours


def lane_records(state_home, repo, t0, t1):
    out = []
    for p in glob.glob(os.path.join(state_home, "lanes", "*.json")):
        try:
            with open(p) as f:
                l = json.load(f)
        except (OSError, ValueError):
            continue
        if repo and l.get("cwd") and not str(l["cwd"]).startswith(repo):
            continue
        start = epoch(l.get("startedAt"))
        if not start or start >= t1 or (epoch(l.get("finishedAt")) or time.time()) < t0:
            continue
        if l.get("status") == "running":
            try:
                os.kill(int(l.get("pid") or 0), 0)
            except (OSError, ValueError):
                l["status"] = "dead"
        out.append(l)
    return out


# ---------------------------------------------------------------- the numbers
def guard_events(state_home, t0, t1):
    """Hours the machine slept and the agents could not run, from `fleet guard`. None without its log."""
    try:
        f = open(os.path.join(state_home, "guard-events.jsonl"))
    except OSError:
        return None
    lost = {"asleep": 0.0, "agent_down": 0.0}
    with f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("kind") in lost and t0 <= (epoch(e.get("ts")) or 0) < t1:
                lost[e["kind"]] += (e.get("seconds") or 0) / 3600
    return lost


def merge_wait_hours(rows, cost, project):
    """Hours each merged ticket sat between its last tester pass and its merge."""
    out = {}
    for t, x in ((cost or {}).get("tickets") or {}).items():
        passed = [epoch(r.get("ts")) or 0 for r in rows if r.get("ticket") == t and r.get("outcome") == "verify_pass"
                  and (not project or r.get("project") == project)]
        if x.get("merged") and passed and x["merged"] > max(passed):
            out[t] = (x["merged"] - max(passed)) / 3600
    return out


def build(t0, t1, project, rows, raw_rows, cost, agents, lanes, codex, prices, now=None):
    """Everything the findings read, as one dict. cost is fleetcost.analyse()'s result."""
    now = now or time.time()
    win = lambda ts: (epoch(ts) or 0) >= t0 and (epoch(ts) or 0) < t1
    is_session = lambda r: r.get("type", "spawn") == "spawn" and not r.get("usage_only") \
        and not (r.get("role") == "pm" and r.get("outcome") in ("done", "retro_fix"))
    wrows = [r for r in rows if r.get("type", "spawn") == "spawn" and not r.get("usage_only") and win(r.get("ts"))
             and (not project or r.get("project") == project)]
    # log hygiene
    dups, seen_ids, last_by_key = [], {}, {}
    for r in sorted((r for r in raw_rows if r.get("type", "spawn") == "spawn" and not r.get("usage_only")
                     and win(r.get("ts")) and (not project or r.get("project") == project)
                     and r.get("outcome") != "retro_fix"), key=lambda r: r.get("ts") or ""):
        key = (r.get("ticket"), r.get("role"), r.get("executor"), r.get("outcome"))
        prev = last_by_key.get(key)
        if prev and (epoch(r.get("ts")) or 0) - (epoch(prev.get("ts")) or 0) <= 600:
            dups.append(r)
        elif r.get("agent_id") and seen_ids.get((r["agent_id"], r.get("outcome"))):
            dups.append(r)
        last_by_key[key] = r
        if r.get("agent_id"):
            seen_ids[(r["agent_id"], r.get("outcome"))] = True
    drop = {}
    for r in dups:
        k = (r.get("ts"), r.get("ticket"), r.get("role"), r.get("executor"), r.get("outcome"))
        drop[k] = drop.get(k, 0) + 1
    sess_rows = []
    for r in wrows:
        k = (r.get("ts"), r.get("ticket"), r.get("role"), r.get("executor"), r.get("outcome"))
        if drop.get(k):
            drop[k] -= 1          # a repeated row is one session, not two
            continue
        if is_session(r):
            sess_rows.append(r)
    tools_by_agent = {a.get("agent_id"): tool_calls(a) for a in agents}
    ct = (cost or {}).get("tickets") or {}
    names = set(t for t in ct) | set(r.get("ticket") for r in sess_rows if r.get("ticket"))
    tickets = []
    for t in sorted(names, key=lambda t: (re.sub(r"\d+$", "", t), int((re.findall(r"\d+$", t) or ["0"])[0]))):
        x = ct.get(t) or {}
        ss = x.get("sessions") or []
        tr = [r for r in sess_rows if r.get("ticket") == t]
        n_eng = max(sum(1 for s in ss if s["role"] == "engineer"),
                    sum(1 for r in tr if r.get("role") == "engineer" and r.get("task_kind") != "rework"))
        fails = [r for r in tr if r.get("outcome") == "verify_fail"]
        n_rew = max(sum(1 for s in ss if s["role"] == "rework"),
                    sum(1 for r in tr if r.get("role") == "engineer" and r.get("task_kind") == "rework"), len(fails))
        n_test = max(sum(1 for s in ss if s["role"] in ("tester", "retest")),
                     sum(1 for r in tr if r.get("role") in ("tester", "verifier-legacy")))
        per = [(s["role"], tools_by_agent.get(s.get("agent_id"), 0)) for s in ss if s.get("agent_id")]
        if ss:
            start = ss[0]["start"]
            end = x.get("merged") or max((s.get("end") or s["start"]) for s in ss)
            hours = (end - start) / 3600
        else:
            hours = sum(r.get("duration_ms") or 0 for r in tr) / 3.6e6 or None
        last = [r for r in tr if r.get("outcome")]
        outcome = f"merged #{x['pr']}" if x.get("merged") else (last[-1]["outcome"] if last else "?")
        tickets.append({"ticket": t, "engineer": n_eng, "rework": n_rew, "tester": n_test,
                        "usd": x.get("cost"), "tools": sum(n for _, n in per) if per else None,
                        "max_tools": max(per, key=lambda p: p[1]) if per else None,
                        "sessions_tools": per, "hours": hours, "outcome": outcome,
                        "causes": [r.get("fail_cause") or r.get("failure_cause") or "none" for r in fails],
                        "tested": any(r.get("outcome") in ("verify_pass", "verify_fail") for r in tr) or n_test > 0})
    # spend: the PM's is counted by whole UTC days, so the agents' share is taken over the same days
    pm = (cost or {}).get("pm") or {}
    day0 = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc).strftime("%Y-%m-%d")
    day1 = datetime.datetime.fromtimestamp(t1, datetime.timezone.utc).strftime("%Y-%m-%d")
    agent_days = sum(fleetcost.usd_by_model(prices, a["by_model"])[0] for a in agents
                     if day0 <= (a.get("first_ts") or "")[:10] <= day1)
    pm_usd = pm.get("usd") or 0.0
    ag = (cost or {}).get("agents") or {}
    agent_usd = ag.get("usd") or 0.0
    share = pm_usd / (pm_usd + agent_days) if (pm_usd + agent_days) else None
    win_agents = [a for a in agents if win(a.get("first_ts"))]
    no_id = [r for r in sess_rows if (r.get("executor") or "claude") == "claude"
             and r.get("role") in ("engineer", "tester") and not r.get("agent_id")]
    # lanes
    lane_fail = [l for l in lanes if l.get("status") in FAIL_LANE or l.get("status") == "dead"]
    log_fail = [r for r in sess_rows if r.get("outcome") == "lane_failed"]
    lane_long = []
    for l in lanes:
        s = epoch(l.get("startedAt"))
        mins = (l.get("durationMs") / 60000) if isinstance(l.get("durationMs"), (int, float)) else \
            (((now - s) / 60) if (l.get("status") == "running" and s) else None)
        if mins is not None:
            lane_long.append((mins, l))
    causes = {}
    for x in tickets:
        for c in x["causes"]:
            causes[c] = causes.get(c, 0) + 1
    tested = [x for x in tickets if x["tested"]]
    hours = (t1 - t0) / 3600
    return {
        "project": project, "since": iso(t0), "until": iso(t1), "hours": hours, "tickets": tickets,
        "spend": {"pm": pm_usd, "agents": agent_usd, "agents_same_days": agent_days, "pm_share": share},
        "pm": {"calls": pm.get("calls"), "ctx_per_call": pm.get("ctx_per_call"), "sessions": pm.get("sessions")},
        "rework": {"tested": len(tested), "reworked": sum(1 for x in tested if x["rework"] > 0),
                   "rate": (sum(1 for x in tested if x["rework"] > 0) / len(tested)) if tested else None,
                   "causes": causes},
        "rewrite_share": (ag.get("rewrite_usd") or 0) / agent_usd if agent_usd else None,
        "duplicates": [{k: r.get(k) for k in ("ts", "ticket", "role", "executor", "outcome", "agent_id", "fail_cause")} for r in dups],
        "missing_agent_id": [{k: r.get(k) for k in ("ts", "ticket", "role")} for r in no_id],
        "lanes": {"n": len(lanes), "failed": [{k: l.get(k) for k in ("ticket", "role", "executor", "status")} for l in lane_fail],
                  "log_failed": len(log_fail),
                  "longest": [{"minutes": round(m), "ticket": l.get("ticket"), "role": l.get("role"),
                               "executor": l.get("executor"), "status": l.get("status")}
                              for m, l in sorted(lane_long, key=lambda p: -p[0])[:3]]},
        "codex": {"pts_per_hour": codex_rate(codex, hours) if codex is not None else None,
                  "samples": len(codex or [])},
        "agent_sessions": len(win_agents),
        "retro_fixes": [{k: r.get(k) for k in ("ts", "ticket", "reason")} for r in wrows if r.get("outcome") == "retro_fix"],
    }


# ---------------------------------------------------------------- findings
def evaluate(d, th, lv):
    F = []

    def add(key, number, shown, cause, fix, who, where=None):
        if lv.get(key) == "off":
            return
        F.append({"key": key, "level": lv.get(key, "warn"), "number": number, "shown": shown,
                  "threshold": th[key], "cause": cause, "fix": fix, "who": who, "where": where or []})

    lost = d.get("lost") or {}
    if sum(lost.values()) > th["lost_hours"]:
        add("lost_hours", sum(lost.values()), f"{lost.get('asleep', 0):.1f}h asleep, {lost.get('agent_down', 0):.1f}h agents unable to run",
            "the machine slept, or the agent login expired",
            "keep the machine on power and awake, and renew the login before a long run.", "owner")

    over = []
    for x in d["tickets"]:
        for role, n in x["sessions_tools"]:
            if n > th["tool_calls_per_session"]:
                over.append((n, f"{x['ticket']} {role} {n}"))
    if over:
        over.sort(reverse=True)
        add("tool_calls_per_session", over[0][0], f"{over[0][0]} tool calls in one session",
            "an agent looping (self-review passes, a slow gate, re-reading) or a ticket wider than one session",
            "send the running agent the soft cap now: stop and report what is done, what is open and the findings left. "
            "Put the cap (3 self-review passes or about 300 tool calls) in every brief.", "pm", [w for _, w in over])
    dear = sorted(((x["usd"], x["ticket"]) for x in d["tickets"] if (x["usd"] or 0) > th["usd_per_ticket"]), reverse=True)
    if dear:
        add("usd_per_ticket", round(dear[0][0], 2), f"{money(dear[0][0])} on one ticket",
            "extra rounds, or one long session",
            "read it with `fleet cost --ticket <id>`. Rounds → the rework-cap ledger (spawn-tester.md). One long "
            "session → the soft cap. Too wide → split it through the planner before the next round.",
            "pm", [f"{t} {money(u)}" for u, t in dear])
    s = d["spend"]["pm_share"]
    if s is not None and s > th["pm_share"]:
        add("pm_share", round(s, 3), f"PM is {pct(s)} of spend",
            "the PM's context is large and every call re-reads it: transcripts, diffs or logs read whole",
            "read review output only through `fleet findings`, send code and log questions to a scan lane, "
            "and compact at the next quiet point (resume note first).", "pm")
    c = d["pm"]["ctx_per_call"]
    if c and c > th["pm_ctx_per_call"]:
        add("pm_ctx_per_call", int(c), f"PM context {ktok(c)} per call",
            "the PM session runs past the compact window, or started without the lower auto-compact setting",
            "write the FLEET RESUME NOTE, then compact (ask the owner to run /compact if you can't). "
            "Start the next PM session with auto-compact near 150k (preflight.md).", "pm")
    many = [(x["rework"], x["ticket"]) for x in d["tickets"] if x["rework"] > th["rework_rounds"]]
    if many:
        many.sort(reverse=True)
        add("rework_rounds", many[0][0], f"{many[0][0]} rework rounds on one ticket",
            "a step let the same class through more than once: the ticket, the build, the test, the review or a brief",
            "find the step before another round and write it in the rework ledger (spawn-tester.md, rework cap); "
            "round 3 goes to the owner.", "pm", [f"{t} {n}" for n, t in many])
    r = d["rework"]
    if r["rate"] is not None and r["tested"] >= 3 and r["rate"] > th["rework_rate"]:
        cs = ", ".join(f"{k} {v}" for k, v in sorted(r["causes"].items(), key=lambda kv: -kv[1])) or "no causes logged"
        add("rework_rate", round(r["rate"], 3), f"{r['reworked']} of {r['tested']} tested tickets went to rework ({cs})",
            "read the causes: missed = build or review; ticket = ticket writing; environment = slots or CI",
            "missed → switch the executor for that kind and brief the whole class; ticket → readiness check before "
            "claim; environment → a ticket for the slot recipe.", "pm")
    tc = r["causes"].get("ticket", 0)
    if tc > th["ticket_cause_failures"]:
        add("ticket_cause_failures", tc, f"{tc} test failure(s) caused by the ticket text",
            "a ticket reached an engineer with a gap: a missing case, a stale path, a decision left open",
            "run the readiness check (pick.md) on every unclaimed ticket in that area, and send the gaps to the "
            "planner's write-ticket skill before claiming.", "pm",
            [x["ticket"] for x in d["tickets"] if "ticket" in x["causes"]])
    if len(d["duplicates"]) > th["duplicate_rows"]:
        add("duplicate_rows", len(d["duplicates"]), f"{len(d['duplicates'])} log row(s) written twice",
            "the same report logged again (a repeated agent notification, or a re-log to add a field)",
            "log each session once; add a missing field with `fleet log backfill`, not a second row. "
            "`fleet log add` refuses repeats unless --force.", "pm",
            [f"{x['ticket']} {x['role']} {x['outcome']} {x['ts']}" for x in d["duplicates"]])
    if len(d["missing_agent_id"]) > th["missing_agent_id"]:
        add("missing_agent_id", len(d["missing_agent_id"]), f"{len(d['missing_agent_id'])} Claude spawn row(s) without agent_id",
            "the spawn was logged without the agent id the Agent call returned",
            "pass `--set agent_id=<id>` on every Claude engineer and tester row, so `fleet cost` ties spend to the ticket.",
            "pm", [f"{x['ticket']} {x['role']} {x['ts']}" for x in d["missing_agent_id"]])
    lf = max(len(d["lanes"]["failed"]), d["lanes"]["log_failed"])
    if lf > th["lane_failures"]:
        add("lane_failures", lf, f"{lf} lane(s) failed, timed out or were stopped",
            "an executor out of budget or rate limited, a lane timeout too short, or a stuck tool",
            "read each lane's result.json error; move that role off the failing executor for this run "
            "(`fleet pick --attempt`), and back off its budget if it was rate limited.", "pm",
            [f"{x['ticket']} {x['role']} {x['executor']} {x['status']}" for x in d["lanes"]["failed"]])
    rs = d["rewrite_share"]
    if rs is not None and rs > th["rewrite_share"]:
        add("rewrite_share", round(rs, 3), f"{pct(rs)} of agent spend went to cache rewrites after long waits",
            "agents blocking longer than the 5-minute prompt cache, or ending their turn to wait",
            "brief waits of at most 4 minutes and background waits through `fleet watch` (standing brief).", "pm")
    long = [x for x in d["lanes"]["longest"] if x["minutes"] > th["lane_minutes"]]
    if long:
        add("lane_minutes", long[0]["minutes"], f"a lane ran {long[0]['minutes']} min",
            "a stuck lane or a ticket too big for one lane",
            "check it with `fleet status`; stop a stuck lane and judge its commits before a fallback builds on them "
            "(spawn.md).", "pm", [f"{x['ticket']} {x['role']} {x['executor']} {x['minutes']} min {x['status']}" for x in long])
    cr = d["codex"]["pts_per_hour"]
    if cr is not None and cr > th["codex_pts_per_hour"]:
        add("codex_pts_per_hour", round(cr, 2), f"Codex used {cr:.1f} weekly points per hour",
            "too many or too long Codex lanes for the weekly budget",
            "decide whether to keep this pace; meanwhile route light roles (scans, reviews) to free models or Claude.",
            "owner")
    return F


def mark_repeats(findings, state_file, now, record=True):
    try:
        with open(state_file) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {"runs": []}
    prev = [r for r in st.get("runs", []) if REPEAT_MIN_S <= now - r.get("at", 0) <= REPEAT_MAX_S]
    keys = set(prev[-1]["keys"]) if prev else set()
    for f in findings:
        f["repeat"] = f["key"] in keys
    if record:
        st["runs"] = (st.get("runs", []) + [{"at": now, "keys": [f["key"] for f in findings]}])[-20:]
        try:
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            tmp = state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(st, f)
            os.replace(tmp, state_file)
        except OSError:
            pass
    return findings


# ---------------------------------------------------------------- render
def render(d, findings, merge_error=None):
    L = []
    until = "now" if d.get("until_is_now") else local(epoch(d["until"]))
    L.append(f"Fleet retro · {d['project']} · {local(epoch(d['since']))} to {until} · {d['hours']:.1f}h")
    s = d["spend"]
    L.append(f"Spend: agents {money(s['agents'])}, PM {money(s['pm'])}"
             + (f" · PM {pct(s['pm_share'])} of spend (by whole UTC day)" if s["pm_share"] is not None else "")
             + (f" · PM {d['pm']['calls']:,} calls, {ktok(d['pm']['ctx_per_call'])} context per call" if d["pm"].get("calls") else ""))
    r = d["rework"]
    cs = ", ".join(f"{k} {v}" for k, v in sorted(r["causes"].items(), key=lambda kv: -kv[1]))
    L.append(f"Tickets: {len(d['tickets'])} · rework on {r['reworked']} of {r['tested']} tested"
             + (f" ({pct(r['rate'])})" if r["rate"] is not None else "") + (f" · causes: {cs}" if cs else "")
             + (f" · {len(d['retro_fixes'])} retro fix(es) applied" if d["retro_fixes"] else ""))
    if merge_error:
        L.append(f"  merges: {merge_error}")
    if d["tickets"]:
        L.append(f"  {'ticket':<14}{'eng':>4}{'rew':>4}{'test':>5}{'spend':>9}{'tools':>7}{'hours':>7}  outcome")
        tot = [0, 0, 0, 0.0, 0]
        for x in d["tickets"]:
            tot[0] += x["engineer"]; tot[1] += x["rework"]; tot[2] += x["tester"]
            tot[3] += x["usd"] or 0; tot[4] += x["tools"] or 0
            tools = x["tools"] if x["tools"] is not None else "—"
            hrs = f"{x['hours']:.1f}" if x["hours"] else "—"
            L.append(f"  {x['ticket']:<14}{x['engineer']:>4}{x['rework']:>4}{x['tester']:>5}{money(x['usd']):>9}"
                     f"{tools:>7}{hrs:>7}  {x['outcome']}")
        L.append(f"  {'total':<14}{tot[0]:>4}{tot[1]:>4}{tot[2]:>5}{money(tot[3]):>9}{tot[4]:>7}")
    ln = d["lanes"]
    cr = d["codex"]["pts_per_hour"]
    L.append(f"Lanes: {ln['n']} in the window, {max(len(ln['failed']), ln['log_failed'])} failed"
             + (f", longest {ln['longest'][0]['minutes']} min" if ln["longest"] else "")
             + " · Codex meter: " + (f"{cr:+.1f} points/h" if cr is not None else "not readable"))
    wait = d.get("merge_wait") or {}
    if d.get("lost") is not None or wait:
        parts = []
        if d.get("lost") is not None:
            parts.append(f"asleep {d['lost']['asleep']:.1f}h, agents down {d['lost']['agent_down']:.1f}h")
        if wait:
            parts.append(f"tester pass to merge: average {sum(wait.values()) / len(wait):.1f}h, longest {max(wait.values()):.1f}h")
        L.append("Lost time: " + " · ".join(parts))
    alerts = [f for f in findings if f["level"] == "alert"]
    L.append("")
    if not findings:
        L.append("FINDINGS: none · healthy")
        return "\n".join(L)
    L.append(f"FINDINGS: {len(alerts)} alert, {len(findings) - len(alerts)} warn"
             "  (pm: apply now · toolkit, owner: propose with the evidence)")
    for f in sorted(findings, key=lambda f: (f["level"] != "alert", f["who"] != "pm", f["key"])):
        L.append(f"  {f['level'].upper():<6}{f['who']:<8}{f['key']}: {f['shown']} (limit {f['threshold']})"
                 + ("  REPEAT" if f.get("repeat") else ""))
        if f["where"]:
            L.append("        where: " + ", ".join(f["where"][:6]) + (f" (+{len(f['where']) - 6} more)" if len(f["where"]) > 6 else ""))
        L.append(f"        cause: {f['cause']}")
        L.append(f"        fix:   {f['fix']}")
    return "\n".join(L)


# ---------------------------------------------------------------- entry
def run(fleetctl, args):
    """Called by fleetctl.main for `retro`."""
    cwd = args.cwd or os.getcwd()
    reg = fleetctl.load_registry(cwd, args.project)
    cfg = fleetctl.project_config(cwd)
    project = args.project or reg.get("_project")
    now = time.time()
    t1 = epoch(args.until) if args.until else now
    if args.until and t1 is None:
        raise SystemExit(f"fleet retro: --until {args.until!r} is not an ISO time")
    if args.since:
        t0 = epoch(args.since)
        if t0 is None:
            raise SystemExit(f"fleet retro: --since {args.since!r} is not an ISO time")
    else:
        t0 = t1 - (args.hours or 24) * 3600
    th, lv = thresholds(cfg)
    repo = fleetctl.git(cwd, "rev-parse", "--show-toplevel") or cwd
    common = fleetctl.git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    main_repo = os.path.dirname(common.rstrip("/")) if common else repo
    identifier = (cfg.get("plane") or {}).get("identifier")
    trunk = (cfg.get("git") or {}).get("trunk")
    prices = reg.get("prices") or {}
    cost_cfg = (cfg.get("fleet") or {}).get("cost") or {}
    dirs = fleetcost.project_dirs(main_repo, cost_cfg.get("claude_project_dirs") or (), args.claude_dir)
    mains, agents = fleetcost.collect(dirs, os.path.join(fleetctl.STATE_HOME, "cost-cache"), identifier)
    rows = fleetctl.load_rows(reg)
    proj_rows = [r for r in rows if not project or r.get("project") == project]
    raw = []
    try:
        with open(fleetctl.P(reg, "path")) as f:
            for line in f:
                try:
                    raw.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    lane_rows = fleetcost.lane_sessions(rows, project)
    prs, err = fleetcost.merged_prs(main_repo, trunk, iso(t0)[:10])
    cost = fleetcost.analyse(mains, agents, lane_rows, prs, prices, identifier, iso(t0), iso(t1) if args.until else None, proj_rows)
    codex_cfg = fleetctl.budget_cfg(reg, "codex")
    codex = codex_samples(codex_cfg.get("sessions_dir"), t0, t1) if codex_cfg.get("source") == "codex-session-log" else None
    lanes = lane_records(fleetctl.STATE_HOME, main_repo, t0, t1)
    d = build(t0, t1, project, proj_rows, raw, cost, agents, lanes, codex, prices, now)
    d["until_is_now"] = not args.until
    d["lost"] = guard_events(fleetctl.STATE_HOME, t0, t1)
    d["merge_wait"] = merge_wait_hours(proj_rows, cost, project)
    findings = evaluate(d, th, lv)
    mark_repeats(findings, os.path.join(fleetctl.STATE_HOME, "retro", f"{project}.json"), now,
                 record=not args.no_record and not args.until)
    if args.json:
        print(json.dumps({**d, "thresholds": th, "levels": lv, "findings": findings, "merge_error": err}, indent=2, default=str))
    else:
        print(render(d, findings, err))
    return 3 if any(f["level"] == "alert" for f in findings) else 0


# ---------------------------------------------------------------- selftest
def selftest(check, fleetctl):
    """A temp outcome log and a made-up cost result through build, evaluate and render."""
    import tempfile
    d = tempfile.mkdtemp(prefix="fleetretro-selftest-")
    log = os.path.join(d, "executor-outcomes.jsonl")
    t0 = epoch("2026-10-01T00:00:00Z")
    ts = lambda m: iso(t0 + m * 60)
    rows = [
        {"ts": ts(10), "ticket": "ST-1", "role": "engineer", "executor": "claude", "model": "opus", "outcome": "pr_opened", "agent_id": "e1"},
        {"ts": ts(40), "ticket": "ST-1", "role": "tester", "executor": "claude", "model": "opus", "outcome": "verify_fail", "fail_cause": "ticket", "agent_id": "t1"},
        {"ts": ts(41), "ticket": "ST-1", "role": "tester", "executor": "claude", "model": "opus", "outcome": "verify_fail"},
        {"ts": ts(60), "ticket": "ST-1", "role": "engineer", "task_kind": "rework", "executor": "claude", "model": "opus", "outcome": "pr_opened", "agent_id": "e2"},
        {"ts": ts(80), "ticket": "ST-1", "role": "tester", "executor": "claude", "model": "opus", "outcome": "verify_fail", "fail_cause": "missed", "agent_id": "t2"},
        {"ts": ts(90), "ticket": "ST-1", "role": "engineer", "task_kind": "rework", "executor": "claude", "model": "opus", "outcome": "pr_opened", "agent_id": "e3"},
        {"ts": ts(95), "ticket": "ST-1", "role": "tester", "executor": "claude", "model": "opus", "outcome": "verify_fail", "fail_cause": "missed", "agent_id": "t3"},
        {"ts": ts(20), "ticket": "ST-2", "role": "engineer", "executor": "claude", "model": "sonnet", "outcome": "pr_opened"},
        {"ts": ts(30), "ticket": "ST-2", "role": "tester", "executor": "codex", "model": "gpt-x", "outcome": "verify_pass"},
        {"ts": ts(31), "ticket": "ST-2", "role": "pm", "executor": "claude", "model": "opus", "outcome": "retro_fix", "reason": "x"},
        {"ts": ts(32), "ticket": "ST-3", "role": "engineer", "executor": "claude", "model": "opus", "outcome": "pr_opened", "agent_id": "e9"},
        {"ts": ts(33), "ticket": "ST-3", "role": "tester", "executor": "claude", "model": "opus", "outcome": "verify_pass", "agent_id": "t9"},
        {"ts": iso(t0 - 3600), "ticket": "ST-0", "role": "engineer", "executor": "claude", "model": "opus", "outcome": "pr_opened"},
    ]
    with open(log, "w") as f:
        for r in rows:
            f.write(json.dumps({"type": "spawn", "project": "st", **r}) + "\n")
    reg = {"log": {"path": log}}
    loaded = fleetctl.load_rows(reg)
    raw = [json.loads(l) for l in open(log)]
    act = lambda n: {"read": {"claude-opus-5-5": [0, 0, 0, 0, 0, n]}, "text": {"claude-opus-5-5": [0, 0, 0, 0, 0, 7]}}
    agents = [{"agent_id": "e1", "activity": act(576), "first_ts": ts(1), "by_model": {}},
              {"agent_id": "t1", "activity": act(40), "first_ts": ts(20), "by_model": {}}]
    cost = {"tickets": {"ST-1": {"sessions": [{"role": "engineer", "start": t0 + 60, "end": t0 + 600, "agent_id": "e1"},
                                              {"role": "tester", "start": t0 + 1200, "end": t0 + 2400, "agent_id": "t1"}],
                                 "cost": 21.5, "rework": 2}},
            "pm": {"usd": 68.0, "calls": 873, "ctx_per_call": 224000, "sessions": 1},
            "agents": {"usd": 62.0, "rewrite_usd": 3.0}}
    lanes = [{"ticket": "ST-2", "role": "tester", "executor": "codex", "status": "timeout", "durationMs": 90 * 60000,
              "startedAt": ts(30)},
             {"ticket": "ST-1", "role": "engineer", "executor": "codex", "status": "aborted", "durationMs": 5 * 60000,
              "startedAt": ts(5)}]
    codex = [(t0 + 60, 10.0, 1), (t0 + 3600, 18.0, 1)]
    data = build(t0, t0 + 2 * 3600, "st", loaded, raw, cost, agents, lanes, codex, {}, now=t0 + 2 * 3600)
    by = {x["ticket"]: x for x in data["tickets"]}
    check("retro: ST-0 before the window is left out", "ST-0" in by, False)
    check("retro: rounds per ticket, a repeated row counted once", (by["ST-1"]["engineer"], by["ST-1"]["rework"], by["ST-1"]["tester"]), (1, 3, 3))
    check("retro: tool calls from the sessions", (by["ST-1"]["tools"], by["ST-1"]["max_tools"]), (616, ("engineer", 576)))
    check("retro: a retro_fix row is not a session", by["ST-2"]["engineer"] + by["ST-2"]["tester"], 2)
    check("retro: causes", data["rework"]["causes"], {"ticket": 1, "missed": 2})
    check("retro: duplicate row found", [(x["ticket"], x["ts"]) for x in data["duplicates"]], [("ST-1", ts(41))])
    check("retro: rows without agent_id", sorted(x["ticket"] for x in data["missing_agent_id"]), ["ST-2"])
    check("retro: codex rate", round(data["codex"]["pts_per_hour"], 1), 4.0)
    th, lv = thresholds({"fleet": {"retro": {"codex_pts_per_hour": 3, "rework_rate": 0.3, "levels": {"rewrite_share": "off"}}}})
    F = {f["key"]: f for f in evaluate(data, th, lv)}
    check("retro: findings fire", sorted(F), sorted(["tool_calls_per_session", "usd_per_ticket", "pm_share", "pm_ctx_per_call",
                                                     "rework_rounds", "rework_rate", "ticket_cause_failures", "duplicate_rows",
                                                     "missing_agent_id", "lane_failures", "lane_minutes", "codex_pts_per_hour"]))
    check("retro: a finding carries number, limit, cause, fix, who",
          (F["tool_calls_per_session"]["number"], F["tool_calls_per_session"]["threshold"], F["tool_calls_per_session"]["who"],
           bool(F["tool_calls_per_session"]["fix"] and F["tool_calls_per_session"]["cause"])), (576, 300, "pm", True))
    check("retro: config sets a threshold", F["codex_pts_per_hour"]["threshold"], 3)
    check("retro: a level can switch a check off", "rewrite_share" in F, False)
    check("retro: PM share by the same days", round(data["spend"]["pm_share"], 2), 1.0)
    state = os.path.join(d, "retro", "st.json")
    now = t0 + 10 * 3600
    mark_repeats(evaluate(data, th, lv), state, now)
    again = mark_repeats(evaluate(data, th, lv), state, now + 30 * 60)
    check("retro: a finding seen 30 min ago is a repeat", all(f["repeat"] for f in again), True)
    soon = mark_repeats(evaluate(data, th, lv), state, now + 35 * 60, record=False)
    check("retro: a run 5 min after the last one compares with the one before", all(f["repeat"] for f in soon), True)
    out = render(data, list(F.values()))
    check("retro: text names the findings", ("FINDINGS:" in out, "tool_calls_per_session" in out, "ST-1" in out), (True, True, True))
    calm = build(t0, t0 + 3600, "st", [], [], {"tickets": {}, "pm": {}, "agents": {}}, [], [], None, {}, now=t0 + 3600)
    check("retro: an empty window is healthy", (evaluate(calm, *thresholds({})), "healthy" in render(calm, [])), ([], True))
    import shutil
    shutil.rmtree(d, ignore_errors=True)
