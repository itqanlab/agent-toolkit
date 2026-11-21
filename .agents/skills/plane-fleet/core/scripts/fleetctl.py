#!/usr/bin/env python3
"""fleetctl — executor selection, budget, outcomes log and scoreboard for the Plane fleet.

One module, used by the PM (through the fleet command), by run-lane.mjs before it launches a lane,
and by the Claude usage-pacer hook. Standard library only. Never prints secrets.

  fleetctl.py pick    --role R [--kind K] [--triggers a,b] [--urgent] [--attempt N]
                      [--pair-with exe:model [--pair-experiment]] [--cwd DIR] [--seed N]
  fleetctl.py budget  [status|line|check EXE [--model M]|backoff EXE [--minutes M] [--reason TEXT]|lane-start EXE] [--json]
  fleetctl.py log     add --ticket T --role R --executor E --model M --outcome O [--kind K]
                      [--set k=v ...] [k=v ...] [--from-result <lane>/result.json] [--force]
                      verify_fail: --cause C [--defect D] [--in-list yes|no] [--severity s1|s2|s3] [--repeat yes|no]
                      --outcome spawn: the row written when a session starts; its result row is not a repeat
                      (a row matching one already logged is refused without --force)
  fleetctl.py log     backfill --ticket T --role R --set k=v [k=v ...]
  fleetctl.py stats   [--role R] [--kind K] [--project P] [--json]
  fleetctl.py report  --project P --since ISO [--until ISO]   Done, approvals, tokens, hours (see report -h)
  fleetctl.py cost    [--since ISO] [--until ISO] [--ticket T] [--json] [--backfill]   real spend and time, from the sessions
  fleetctl.py retro   [--since ISO|--hours N] [--cwd DIR] [--json]   the fleet reviews itself (fleetretro.py)
  fleetctl.py review  [--cwd DIR] [--last N] [--md FILE] [--json]   every run measured the same way and kept (fleetreview.py)
  fleetctl.py rounds  [--ticket T] [--cwd DIR] [--json]   failed test rounds per ticket, the cap, one more allowed?
  fleetctl.py rounds  allow <TICKET> --reason "<the owner's words>"   one more rework spawn past the cap
  fleetctl.py queue   add --ticket T --role engineer|tester --slot S --brief FILE | list [--all] | next [--pop]
                      (next: exit 3 when the machine gate admits no heavy session, 4 when empty)
  fleetctl.py questions add --ticket T [--pr N] --text "..." | list [--all] | close <id> --answer "..."
  fleetctl.py selftest                      log add round trip in a temp log
  fleetctl.py apply   [--dry-run]          promotions / demotions -> user override + decisions log
  fleetctl.py seed                          fold legacy run-log rows (log.legacy_glob) into the log
  fleetctl.py config  [--get a.b.c] [--cwd DIR]   .plane/config.json + the per-user project override
  fleetctl.py free-models [list|refresh] [--json]   the free models opencode serves today (freemodels.py)
  fleetctl.py status  [--cwd DIR] [--json]   budget, slots, lanes, open PRs and CI in one call (fleetstatus.py)
  fleetctl.py held    set T --blocked-by A[,B] | clear T [T ...] | list [--json] [--cwd DIR]
                      Todo tickets skipped for their blockers; status says when one can start stacked
  fleet resources     [--cwd DIR] [--json] [--gate heavy|light] [--wait]   the machine gate (fleetres.py)

Layers, later wins: <this dir>/../executors.json  <  user override (log.user_override)
  <  user override projects.<project>  <  <repo>/.plane/config.json fleet.executors
"""
import argparse, datetime, glob, hashlib, json, os, random, re, subprocess, sys, time
import freemodels

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))       # <fleet root>/core/scripts/
BASE_REGISTRY = os.path.join(FLEET_ROOT, "core", "references", "executors.json")
STATE_HOME = os.environ.get("PLANE_FLEET_HOME") or os.path.expanduser("~/.config/plane-fleet")
OUTCOMES = ("pr_opened", "blocked", "verify_pass", "verify_fail", "done", "lane_failed", "stale", "deferred", "retro_fix", "decision",
            "spawn")
# The row the PM writes when it starts a session (2.14). Its result comes later as a row of its
# own; the start row is never scored and never counted as a session, so nothing counts twice.
START_OUTCOMES = ("spawn",)
# Rows that mark something the PM did, not a session: never scored, never counted as spend.
MARKER_OUTCOMES = ("done", "retro_fix", "decision")
# a session that ended without a result must say why, or the review cannot learn from it
REASON_OUTCOMES = ("blocked", "lane_failed", "deferred", "decision", "verify_fail")
DUPLICATE_WINDOW_S = 600
# Why a tester failed a PR (`core/pm/skills/spawn.md` §3 "Read a low pass rate correctly"); only "missed" counts against the model.
# pm_ruling (2.14): the fail came from a PM scope decision or brief, not from the engineer.
FAIL_CAUSES = ("missed", "ticket", "spec_changed", "environment", "pm_ruling")
# Severity of a tester finding (2.14). s1: data loss, money, a wrong or duplicate send to a
# customer, security, a blocked main path. s2: a visible fault with a workaround. s3: polish.
SEVERITIES = ("s1", "s2", "s3")
# what kind of defect a missed verify_fail was, so the review can count rework by class.
# criterion: an acceptance criterion not met. other_path: the rule works on one path, breaks on
# another the change touches (edit, second screen, error code). stale_state: preview and save
# disagree, or state changed between them. concurrency: race, deadlock, retry duplicate.
# money_rule: rounding, discount share or another money rule applied differently. out_of_scope:
# the ticket never asked for it. stacked: brought in by another ticket on the same branch.
DEFECTS = ("criterion", "other_path", "stale_state", "concurrency", "money_rule", "out_of_scope", "stacked")
def X(p):
    """~ expands; {state_home} is PLANE_FLEET_HOME (default ~/.config/plane-fleet); {fleet_root} is this folder."""
    if not isinstance(p, str):
        return p
    return os.path.expanduser(p.replace("{state_home}", STATE_HOME).replace("{fleet_root}", FLEET_ROOT))


# ---------------------------------------------------------------- registry
def deep_merge(base, over):
    if not isinstance(over, dict) or not isinstance(base, dict):
        return over
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out.get(k), v) if k in out else v
    return out


def read_json(path, default=None):
    try:
        with open(X(path)) as f:
            return json.load(f)
    except Exception:
        return default


def git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def project_of(cwd):
    """Repo name, the same for the main checkout and every worktree of it."""
    if not cwd:
        return None
    common = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        return os.path.basename(os.path.dirname(common.rstrip("/")))
    top = git(cwd, "rev-parse", "--show-toplevel")
    return os.path.basename(top) if top else None


def load_registry(cwd=None, project=None):
    reg = read_json(BASE_REGISTRY, {}) or {}
    sources = [BASE_REGISTRY]
    user_path = X(reg.get("log", {}).get("user_override", "{state_home}/executors.json"))
    user = read_json(user_path, {}) or {}
    project = project or project_of(cwd)
    if user:
        reg = deep_merge(reg, {k: v for k, v in user.items() if k != "projects"})
        sources.append(user_path)
        proj = (user.get("projects") or {}).get(project or "")
        if proj:
            reg = deep_merge(reg, proj)
            sources.append(f"{user_path} projects.{project}")
    top = git(cwd, "rev-parse", "--show-toplevel") if cwd else None
    if top:
        cfg = read_json(os.path.join(top, ".plane/config.json"), {}) or {}
        over = (cfg.get("fleet") or {}).get("executors")
        if isinstance(over, dict):
            reg = deep_merge(reg, over)
            sources.append(os.path.join(top, ".plane/config.json") + " fleet.executors")
    reg["_sources"] = sources
    reg["_project"] = project
    return reg


def P(reg, key):
    return X(reg.get("log", {}).get(key, ""))


# ---------------------------------------------------------------- budget
def hhmm(ts):
    if not ts:
        return "?"
    return datetime.datetime.fromtimestamp(ts).astimezone().strftime("%H:%M")


def budget_cfg(reg, exe):
    b = reg.get("budget", {})
    user = read_json(P(reg, "budget_override") or X("{state_home}/budget.json"), {}) or {}
    b = deep_merge(b, user)
    cfg = dict(b.get("defaults", {}))
    cfg.update({k: v for k, v in (b.get("executors", {}).get(exe) or {}).items() if v is not None or k not in cfg})
    return cfg


def switch_on(reg, exe, name):
    d = os.path.dirname(P(reg, "path")) or STATE_HOME
    files = [os.path.join(d, name), os.path.join(d, f"{name}-{exe}")]
    legacy = budget_cfg(reg, exe).get("legacy_switch_dir")
    if legacy:
        files.append(os.path.join(X(legacy), name))
    return any(os.path.exists(f) for f in files)


def state_path(reg, exe):
    d = P(reg, "state_dir") or os.path.join(STATE_HOME, "state")
    os.makedirs(d, exist_ok=True)
    # Executors on one plan (opencode and claude-ollama on Ollama Cloud) share one counter and back-off.
    exe = budget_cfg(reg, exe).get("state_as") or exe
    return os.path.join(d, f"{exe}.json")


def read_state(reg, exe):
    return read_json(state_path(reg, exe), {}) or {}


def write_state(reg, exe, st):
    p = state_path(reg, exe)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, p)


def meter_claude(cfg, now):
    f = X(cfg.get("status_file"))
    if not f:
        return None, None, "no meter configured (budget.executors.claude.status_file)"
    try:
        age = now - os.path.getmtime(f)
        five = json.load(open(f))["rate_limits"]["five_hour"]
        used, resets = float(five["used_percentage"]), int(five["resets_at"])
    except Exception:
        return None, None, "no meter"
    if cfg.get("stale_minutes") and age > cfg["stale_minutes"] * 60:
        return None, None, f"meter {int(age // 60)} min old"
    return used, resets, None


def meter_codex(cfg, now):
    root = X(cfg.get("sessions_dir", "~/.codex/sessions"))
    files = []
    for day in sorted(glob.glob(os.path.join(root, "*", "*", "*")), reverse=True)[:7]:
        files += glob.glob(os.path.join(day, "*.jsonl"))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for path in files[:12]:
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 4_000_000))
                tail = fh.read().decode("utf8", "ignore").splitlines()
        except OSError:
            continue
        for line in reversed(tail):
            if '"rate_limits"' not in line:
                continue
            try:
                rl = json.loads(line)["payload"]["rate_limits"]
            except Exception:
                continue
            if not rl:
                continue
            best = None
            for key in ("primary", "secondary"):
                w = rl.get(key) or None
                if not w or w.get("used_percent") is None:
                    continue
                used, resets = float(w["used_percent"]), int(w.get("resets_at") or 0)
                if resets and now >= resets:
                    used = 0.0  # that window has reset since the log line
                cand = (used, resets, int(w.get("window_minutes") or 0))
                if best is None or cand[0] > best[0]:
                    best = cand
            if best is None:
                continue
            if rl.get("rate_limit_reached_type") and best[1] > now:
                return 100.0, best[1], best[2], "limit reached"
            return best[0], best[1], best[2], None
    return None, None, None, "no codex session log with rate_limits"


def antigravity_usage(reg, exe, cfg, now):
    """`agy -p /usage --output-format json` -> {bucket id: (used %, resets_at, window minutes)}.
    The call takes a few seconds, so the answer is cached in the executor's state file."""
    st = read_state(reg, exe)
    cache = st.get("usage") or {}
    if cache.get("buckets") and now - cache.get("at", 0) < float(cfg.get("cache_minutes") or 5) * 60:
        return {k: tuple(v) for k, v in cache["buckets"].items()}, None
    binary = ((reg.get("executors") or {}).get(exe) or {}).get("binary") or "agy"
    try:
        r = subprocess.run([binary, "-p", "/usage", "--output-format", "json"], capture_output=True,
                           text=True, timeout=30, cwd=os.path.expanduser("~"))
        groups = json.loads(r.stdout)["command"]["data"]["groups"]
    except Exception:
        return None, "no meter (agy /usage failed)"
    buckets = {}
    for g in groups:
        for b in g.get("buckets") or []:
            if b.get("remaining_fraction") is None:
                continue
            try:
                resets = datetime.datetime.fromisoformat(str(b.get("reset_time")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                resets = None
            wmin = {"5h": 300, "weekly": 7 * 24 * 60}.get(b.get("window"), 0)
            buckets[b["id"]] = (round((1 - float(b["remaining_fraction"])) * 100, 1), resets, wmin)
    st = read_state(reg, exe)
    st["usage"] = {"at": now, "buckets": buckets}
    write_state(reg, exe, st)
    return buckets, None


def pool_of(cfg, model):
    """The longest `pools` prefix the model starts with; None when the model is unknown."""
    pools = {k: v for k, v in (cfg.get("pools") or {}).items() if not k.startswith("$")}
    keys = [k for k in pools if str(model or "").startswith(k)]
    return max(keys, key=len) if keys else None


def judge(used, resets, window, hard, allow, now, pace=True):
    """Hard stop, then pace: no faster than the window has elapsed plus the allowance."""
    if used >= hard:
        return "stop", resets, None
    if pace and window and resets:
        elapsed = max(0.0, min(1.0, (now - (resets - window)) / window))
        allowed = min(hard, elapsed * 100 + allow)
        if used > allowed:
            catch_up = (resets - window) + (used - allow) / 100 * window
            return "hold", min(catch_up, resets), f"ahead of pace ({allowed:.0f}% allowed now)"
    return "ok", None, None


def budget_check(reg, exe, now=None, model=None):
    now = now or time.time()
    cfg = budget_cfg(reg, exe)
    hard = float(cfg.get("hard_stop_pct", 95))
    allow = float(cfg.get("pace_allowance_pct", 20))
    res = {"executor": exe, "state": "ok", "used_pct": None, "resets_at": None, "resume_at": None,
           "window_minutes": cfg.get("window_minutes"), "note": None, "source": cfg.get("source")}
    if switch_on(reg, exe, "pacer-off"):
        res["note"] = "pacer off"
        return res
    st = read_state(reg, exe)
    if st.get("backoff_until", 0) > now:
        res.update(state="hold", resume_at=st["backoff_until"], note=f"backoff: {st.get('reason', 'rate limited')}")
        return res
    src = cfg.get("source")
    used = resets = None
    window = (cfg.get("window_minutes") or 0) * 60
    if src == "antigravity-usage":
        # Models share quota in pools (Gemini, Claude+GPT, Argon), each with its own windows.
        # With a model, judge its pool; without one, report every pool and judge none.
        buckets, note = antigravity_usage(reg, exe, cfg, now)
        res["note"] = note
        if buckets is None:
            return res
        pools = {k: v for k, v in (cfg.get("pools") or {}).items() if not k.startswith("$")}
        res["pools"] = {p: {b: buckets[b][0] for b in ids if b in buckets} for p, ids in pools.items()}
        if model is None:
            return res
        pool = pool_of(cfg, model)
        if pool is None:
            res["note"] = f"no pool for {model} (budget.executors.{exe}.pools)"
            return res
        res["pool"] = pool
        pace = not switch_on(reg, exe, "pace-off")
        rank = {"ok": 0, "hold": 1, "stop": 2}
        for b in pools[pool]:
            if b not in buckets:
                continue
            u, rs, wmin = buckets[b]
            if rs and now >= rs:
                u = 0.0  # that window has reset since the cached reading
            state, resume, why = judge(u, rs, wmin * 60, hard, allow, now, pace)
            if res["used_pct"] is None or u > res["used_pct"]:
                res.update(used_pct=u, resets_at=rs, window_minutes=wmin)
            if rank[state] > rank[res["state"]] or (state == res["state"] != "ok" and (resume or 0) > (res["resume_at"] or 0)):
                res.update(state=state, resume_at=resume, note=why or f"{b} at {u:.0f}%")
        return res
    if src == "claude-statusline":
        used, resets, note = meter_claude(cfg, now)
        res["note"] = note
    elif src == "codex-session-log":
        used, resets, wmin, note = meter_codex(cfg, now)
        res["note"] = note
        if wmin:
            window = wmin * 60
            res["window_minutes"] = wmin
    elif src == "local-counter":
        wmin = cfg.get("window_minutes") or 300
        window = wmin * 60
        start = st.get("window_start", 0)
        lanes = st.get("lanes", 0) if now - start < window else 0
        res["lanes_in_window"] = lanes
        cap = cfg.get("max_lanes_per_window")
        if cap:
            used = 100.0 * lanes / cap
            resets = (start + window) if lanes else None
        else:
            res["note"] = f"{lanes} lanes this window, no usage API (429 back-off only)"
        if used is None:
            return res
    res["used_pct"], res["resets_at"] = used, resets
    if used is None:
        return res  # unknown meter: no judgement, the skill's own budget rules apply
    state, resume, why = judge(used, resets, window, hard, allow, now, not switch_on(reg, exe, "pace-off"))
    if state != "ok":
        res.update(state=state, resume_at=resume)
        if why:
            res["note"] = why
    return res


def budget_record_lane_start(reg, exe, now=None):
    now = now or time.time()
    cfg = budget_cfg(reg, exe)
    if cfg.get("source") != "local-counter":
        return
    st = read_state(reg, exe)
    window = (cfg.get("window_minutes") or 300) * 60
    if now - st.get("window_start", 0) >= window:
        st["window_start"], st["lanes"] = now, 0
    st["lanes"] = st.get("lanes", 0) + 1
    write_state(reg, exe, st)


def budget_backoff(reg, exe, minutes=None, reason="rate limited", now=None):
    now = now or time.time()
    minutes = minutes or budget_cfg(reg, exe).get("backoff_minutes", 30)
    st = read_state(reg, exe)
    st["backoff_until"] = now + float(minutes) * 60
    st["reason"] = reason
    write_state(reg, exe, st)
    return st["backoff_until"]


LABELS = {"claude": "Claude", "codex": "Codex", "opencode": "Ollama", "claude-ollama": "Claude Code/Ollama",
          "antigravity": "Antigravity"}


def budget_line(reg, checks=None):
    checks = checks or [budget_check(reg, e) for e in reg.get("budget", {}).get("executors", {})]
    parts = []
    for c in checks:
        lab = LABELS.get(c["executor"], c["executor"])
        if c["used_pct"] is not None:
            w = c.get("window_minutes") or 0
            span = "wk" if w >= 7 * 24 * 60 else (f"{w // 60}h" if w else "")
            s = f"{lab} {c['used_pct']:.0f}%" + (f" ({span})" if span else "")
        elif c.get("pools"):
            # the highest bucket per pool, prefixes on the same buckets named once:
            # "Antigravity gemini 12% · gemini-4-argon 0% · claude/gpt 40%"
            same = {}
            for p, v in c["pools"].items():
                if not v:
                    continue
                key = tuple(sorted(v))
                if key in same:
                    same[key][0].append(p)
                else:
                    same[key] = ([p], max(v.values()))
            s = f"{lab} " + " · ".join(f"{'/'.join(ps)} {u:.0f}%" for ps, u in same.values())
        elif c.get("note") == "pacer off":
            s = f"{lab} pacer off"
        elif c.get("source") == "local-counter":
            s = f"{lab} ok ({c.get('lanes_in_window', 0)} lanes)" if c["state"] == "ok" else lab
        else:
            s = f"{lab} ?"
        if c["state"] != "ok":
            s += f" {c['state'].upper()} until {hhmm(c['resume_at'])}"
        parts.append(s)
    return " · ".join(parts)


# ---------------------------------------------------------------- outcomes log
def decode_project_dir(name):
    """'-Volumes-SSD-mine-my-repo' -> 'my-repo' by walking the real filesystem."""
    parts = name.strip("-").split("-")

    def walk(prefix, i):
        if i == len(parts):
            return prefix
        acc = parts[i]
        for j in range(i + 1, len(parts) + 1):
            if j > i + 1:
                acc = acc + "-" + parts[j - 1]
            cand = prefix + "/" + acc
            if os.path.exists(cand):
                got = walk(cand, j)
                if got:
                    return got
        return None

    found = walk("", 0)
    return os.path.basename(found) if found else None


LEGACY_ROLE = {"worker": "engineer", "worker-rework": "engineer", "tester": "tester", "ticket_writer": "ticket-writer",
               "triage": "scan", "pre-merge-verify": "verifier-legacy", "post-deploy-verify": "verifier-legacy"}


def legacy_to_row(r, project, source):
    role = LEGACY_ROLE.get(r.get("role"), r.get("role"))
    kind = r.get("task_kind")
    if not kind:
        trig = str(r.get("trigger") or "")
        if r.get("role") == "worker-rework" or "rework" in trig:
            kind = "rework"
        elif "schema" in trig:
            kind = "schema"
        elif r.get("pilot") == "sonnet-tester":
            kind = "copy-i18n"
        else:
            kind = "unknown"
    row = {"type": "spawn", "ts": r.get("ts"), "project": project, "ticket": r.get("ticket"), "role": role,
           "task_kind": kind, "executor": r.get("executor") or "claude", "model": r.get("model"),
           "experiment": bool(r.get("pilot")), "reason": r.get("trigger") or ("pilot " + r["pilot"] if r.get("pilot") else None),
           "duration_ms": r.get("duration_ms"), "tokens": r.get("tokens"), "outcome": r.get("outcome"),
           "verify_first_pass": r.get("verify_first_pass"), "rework_count": r.get("rework_count"),
           "source": source, "source_key": f"{source}|{r.get('ts')}|{r.get('ticket')}|{r.get('role')}"}
    for k in ("escalated", "context_pressure", "note", "fail_cause", "failure_cause", "ci_first_pass", "reverted", "bug_filed"):
        if r.get(k) is not None:
            row[k] = r[k]
    return row


def legacy_rows(reg):
    out = []
    for f in sorted(glob.glob(P(reg, "legacy_glob") or "")) if P(reg, "legacy_glob") else []:
        project = decode_project_dir(os.path.basename(os.path.dirname(f))) or os.path.basename(os.path.dirname(f))
        src = os.path.basename(os.path.dirname(f)) + "/" + os.path.basename(f)
        try:
            for line in open(f):
                line = line.strip()
                if line:
                    try:
                        out.append(legacy_to_row(json.loads(line), project, src))
                    except Exception:
                        pass
        except OSError:
            pass
    return out


def legacy_identity(r):
    """A legacy row's identity without the folder it was read from. A repo that moves gets a
    new Claude projects folder with a copy of its old run log; both copies are one row."""
    k = r.get("source_key")
    if not k or "|" not in k:
        return None
    src, rest = k.split("|", 1)
    return (r.get("project"), os.path.basename(src), rest)


def load_rows(reg):
    """Spawn rows with back-fills applied. Legacy files are read live and win over seeded copies."""
    spawns, backfills = [], []
    try:
        for line in open(P(reg, "path")):
            try:
                r = json.loads(line)
            except Exception:
                continue
            (backfills if r.get("type") == "backfill" else spawns).append(r)
    except OSError:
        pass
    live = {}
    for r in legacy_rows(reg):
        live.setdefault(legacy_identity(r), r)
    merged, seen = [], set()
    for r in spawns:
        k = legacy_identity(r)
        if k is None:
            merged.append(r)
        elif k not in seen:
            seen.add(k)
            merged.append(live.pop(k, r))
    merged += [r for k, r in live.items() if k not in seen]
    merged.sort(key=lambda r: r.get("ts") or "")
    merged = fold_usage_rows(merged)
    for b in sorted(backfills, key=lambda r: r.get("ts") or ""):
        for r in reversed(merged):
            if (r.get("ticket"), r.get("role")) == (b.get("ticket"), b.get("role")) and \
               (not b.get("project") or r.get("project") == b.get("project")) and (r.get("ts") or "") <= (b.get("ts") or "~"):
                r.update(b.get("fields", {}))
                break
    derive_quality(merged)
    return merged


def fold_usage_rows(rows):
    """Back-filled usage rows ("usage_only": true) carry tokens/duration for a session whose own
    spawn row was logged without them. With "for_ts" naming that spawn row (same project, ticket,
    role, ts) the numbers go onto it and the usage row disappears, so a session is counted once.
    Without a match the usage row stays as a session of its own."""
    index = {}
    for r in rows:
        if not r.get("usage_only"):
            index.setdefault((r.get("project"), r.get("ticket"), r.get("role"), r.get("ts")), r)
    out = []
    for r in rows:
        if r.get("usage_only") and r.get("for_ts"):
            target = index.get((r.get("project"), r.get("ticket"), r.get("role"), r.get("for_ts")))
            if target is not None:
                for k, v in r.items():
                    if k in NUMERIC_KEYS or k in ("lane_status", "result_path", "agent_id", "usage_source"):
                        if target.get(k) is None:
                            target[k] = v
                target["backfilled"] = True
                continue
        out.append(r)
    return out


def not_the_models_fault(row):
    """A verify_fail whose recorded cause is anything but "missed". Rows from before causes were
    required carry none and still count, as they always did."""
    cause = row.get("fail_cause") or row.get("failure_cause")
    return row.get("outcome") == "verify_fail" and bool(cause) and cause != "missed"


def derive_quality(rows):
    """'quality' = the signal each role is scored on.
    engineer: verify_first_pass if set, else the first tester verdict after it on the same ticket
              (legacy rows put the engineer's first-pass flag on the tester row).
    tester:   verdict held = not reverted and no bug filed, only once those are back-filled.
    others:   verify_first_pass if set."""
    by_ticket = {}
    for r in rows:
        by_ticket.setdefault((r.get("project"), r.get("ticket")), []).append(r)
    for r in rows:
        role = r.get("role")
        q = r.get("verify_first_pass") if isinstance(r.get("verify_first_pass"), bool) else None
        if q is False and not_the_models_fault(r):
            q = None
        if role == "engineer" and q is None and r.get("outcome") in ("pr_opened", "done", "verify_pass", "verify_fail"):
            for t in by_ticket.get((r.get("project"), r.get("ticket")), []):
                if t.get("role") in ("tester", "verifier-legacy") and (t.get("ts") or "") > (r.get("ts") or "") \
                        and t.get("outcome") in ("verify_pass", "verify_fail"):
                    # A fail the tester put on the ticket, the spec, the environment or a PM ruling
                    # says nothing about the engineer's model, so it is not scored either way.
                    q = None if not_the_models_fault(t) else t.get("outcome") == "verify_pass"
                    break
        elif role == "tester":
            q = None
            if "reverted" in r or "bug_filed" in r:
                q = not r.get("reverted") and not r.get("bug_filed")
        r["quality"] = q


def duplicate_of(reg, row, now=None):
    """The logged row this new one repeats, or None. A repeat is the same project, ticket, role,
    executor and outcome within DUPLICATE_WINDOW_S, or the same agent_id with the same outcome.
    A retro_fix or decision row is never a repeat: two of them can land in one minute."""
    if row.get("outcome") in ("retro_fix", "decision"):
        return None
    now = now or time.time()
    key = (row.get("project"), row.get("ticket"), row.get("role"), row.get("executor"), row.get("outcome"))
    hit = None
    try:
        with open(P(reg, "path")) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("type", "spawn") != "spawn" or r.get("usage_only"):
                    continue
                if row.get("agent_id") and r.get("agent_id") == row.get("agent_id") and r.get("outcome") == row.get("outcome"):
                    hit = r
                    continue
                if (r.get("project"), r.get("ticket"), r.get("role"), r.get("executor"), r.get("outcome")) == key:
                    t = parse_ts(r.get("ts"))
                    if t and 0 <= now - t.timestamp() <= DUPLICATE_WINDOW_S:
                        hit = r
    except OSError:
        return None
    return hit


def append_row(reg, row):
    path = P(reg, "path")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


NUMERIC_KEYS = ("duration_ms", "tokens", "input_tokens", "output_tokens", "cached_input_tokens",
                "reasoning_output_tokens", "rework_count", "claude_meter_delta_pct", "tool_uses", "usd")


def coerce(key, v):
    """key=value text -> number for the numeric keys (1,234 and 1_234 allowed), true/false/null
    -> bool/None, JSON objects and quoted strings as JSON, anything else stays a string."""
    s = v.strip()
    if key in NUMERIC_KEYS:
        n = s.replace(",", "").replace("_", "")
        try:
            return int(n)
        except ValueError:
            try:
                return float(n)
            except ValueError:
                raise SystemExit(f"fleetctl: {key} must be a number, got {v!r}")
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if s.lower() in ("null", "none"):
        return None
    try:
        return json.loads(s)
    except Exception:
        return v


def parse_kv(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"fleetctl: expected key=value, got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = coerce(k.strip(), v)
    return out


def usage_fields(usage):
    """A codex/opencode usage block -> flat numeric fields; tokens = input + output."""
    out = {}
    if not isinstance(usage, dict):
        return out
    for k in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
        if isinstance(usage.get(k), (int, float)):
            out[k] = usage[k]
    if "input_tokens" in out or "output_tokens" in out:
        out["tokens"] = out.get("input_tokens", 0) + out.get("output_tokens", 0)
    return out


def lane_result_fields(path):
    """A lane's result.json -> (identity, fields). identity: ticket/role/executor/model, used
    where the command line leaves them out. fields: duration_ms, the token counts, lane_status."""
    try:
        res = json.load(open(X(path)))
    except Exception as e:
        raise SystemExit(f"fleetctl: cannot read {path}: {e}")
    ident = {k: res.get(k) for k in ("ticket", "role", "executor", "model", "effort") if res.get(k)}
    fields = {"result_path": os.path.abspath(X(path))}
    if isinstance(res.get("durationMs"), (int, float)):
        fields["duration_ms"] = res["durationMs"]
    fields.update(usage_fields(res.get("usage")))
    if res.get("status") and res["status"] != "completed":
        fields["lane_status"] = res["status"]
    return ident, fields, res


def lane_reason(res):
    """A reason taken from a lane's own result, marked as the lane's words; None when it said nothing."""
    if not res:
        return None
    lines = [l.strip() for l in str(res.get("lastMessage") or res.get("error") or "").splitlines() if l.strip()]
    if lines:
        return "lane said: " + lines[-1][:200]
    if res.get("status") and res["status"] != "completed":
        return f"lane status {res['status']}"
    return None


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- stats
def cost_units(reg, r):
    w = reg.get("cost_weights", {})
    key = f"{r.get('executor')}:{r.get('model')}"
    provider = str(r.get("model") or "").split("/", 1)[0] + "/" if "/" in str(r.get("model") or "") else None
    weight = w.get(key, w.get(f"{r.get('executor')}:{provider}") if provider else None)
    if weight is None:
        weight = w.get(r.get("executor") or "", None)
    tok = r.get("tokens")
    if isinstance(tok, dict):  # codex usage block (older rows)
        tok = (tok.get("input_tokens", 0) - tok.get("cached_input_tokens", 0)) + tok.get("output_tokens", 0)
    elif isinstance(r.get("input_tokens"), (int, float)):  # flat lane usage: cache reads are not billed alike
        tok = (r["input_tokens"] - (r.get("cached_input_tokens") or 0)) + (r.get("output_tokens") or 0)
    if weight is None or not isinstance(tok, (int, float)):
        return None
    return tok / 1e6 * weight


def summarize(reg, rows):
    fp = [r["quality"] for r in rows if isinstance(r.get("quality"), bool)]
    rw = [r["rework_count"] for r in rows if isinstance(r.get("rework_count"), (int, float))]
    du = [r["duration_ms"] for r in rows if isinstance(r.get("duration_ms"), (int, float))]
    co = [c for c in (cost_units(reg, r) for r in rows) if c is not None]
    fp_sorted = [r["quality"] for r in sorted(rows, key=lambda r: r.get("ts") or "") if isinstance(r.get("quality"), bool)]
    return {"n": len(rows), "n_fp": len(fp), "first_pass": (sum(fp) / len(fp)) if fp else None,
            "rework_rate": (sum(1 for x in rw if x > 0) / len(rw)) if rw else None,
            "mean_duration_min": (sum(du) / len(du) / 60000) if du else None,
            "mean_cost": (sum(co) / len(co)) if co else None, "recent_fp": fp_sorted}


def scoreboard(reg, rows, role=None, kind=None, project=None):
    groups = {}
    for r in rows:
        if r.get("type", "spawn") != "spawn" or r.get("outcome") in ("deferred", *START_OUTCOMES) or r.get("usage_only"):
            continue
        if r.get("role") == "pm" and r.get("outcome") in MARKER_OUTCOMES:  # a PM marker, not a session
            continue
        if role and r.get("role") != role:
            continue
        if project and r.get("project") != project:
            continue
        exe = rkey(r)
        for k in dict.fromkeys((r.get("task_kind") or "unknown", "*")):  # a row logged as "*" counts once
            if kind and k != kind:
                continue
            groups.setdefault((r.get("role"), k, exe), []).append(r)
    return {key: summarize(reg, rs) for key, rs in groups.items()}


def fmt_pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def print_board(reg, board):
    m = reg.get("selection", {}).get("min_samples", 5)
    print(f"{'role':<15}{'kind':<18}{'executor:model':<30}{'n':>4}{'fp n':>6}{'first-pass':>11}{'rework':>8}{'min':>6}{'cost':>7}")
    for (role, kind, exe), s in sorted(board.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] != "*", kv[0][1], -kv[1]["n"])):
        rate = fmt_pct(s["first_pass"]) if s["n_fp"] >= m else ("not enough data" if s["n_fp"] else "—")
        dur = f"{s['mean_duration_min']:.0f}" if s["mean_duration_min"] is not None else "—"
        cost = f"{s['mean_cost']:.2f}" if s["mean_cost"] is not None else "—"
        print(f"{role or '?':<15}{kind:<18}{exe:<30}{s['n']:>4}{s['n_fp']:>6}{rate:>16}{fmt_pct(s['rework_rate']):>8}{dur:>6}{cost:>7}"[:200])


# ---------------------------------------------------------------- pick
def ckey(c):
    # effort is part of a candidate's identity: the same model at two efforts is two candidates
    return f"{c['executor']}:{c['model']}" + (f"@{c['effort']}" if c.get("effort") else "")


def rkey(r):
    return ckey({"executor": r.get("executor") or "claude", "model": r.get("model"), "effort": r.get("effort")})


def family(reg, c):
    fam = reg.get("families", {})
    # '<executor>:<prefix>' first, then '*:<prefix>' (open models served by more than one executor).
    model = str(c["model"]).split("/", 1)[-1]  # "opencode/nemotron-..." is still nemotron
    for scope in (c["executor"], "*"):
        for k, v in fam.items():
            if k.startswith(scope + ":") and model.startswith(k.split(":", 1)[1]):
                return v
    return fam.get(c["executor"], c["executor"])


def candidates_for(reg, role, kind, notes=None):
    """The role's list for this kind, with free models added or removed by free_model_policy."""
    table = (reg.get("candidates") or {}).get(role) or {}
    lst = table.get(kind) if kind and kind in table else table.get("*")
    cands, n = freemodels.apply_policy(reg, role, [c for c in (lst or []) if isinstance(c, dict)],
                                       freemodels.load_state(STATE_HOME))
    if notes is not None:
        notes.extend(n)
    return cands, (kind if kind in table else "*")


def pick(reg, role, kind=None, triggers=(), urgent=False, attempt=0, pair_with=None, pair_experiment=False, rng=random):
    sel = reg.get("selection", {})
    kinds = reg.get("task_kinds", {})
    kind = kind or "*"
    out = {"role": role, "task_kind": kind, "experiment": False, "registry": reg.get("_sources"), "project": reg.get("_project")}
    esc = (reg.get("escalation") or {}).get(role) or {}
    fired = [t for t in triggers if t in (esc.get("triggers") or [])]
    portable = role in sel.get("portable_roles", [])
    if fired:
        cands, list_kind, pinned = [esc["to"]], "escalation", True
        out["reason"] = "escalated: " + ", ".join(fired)
    else:
        free_notes = []
        cands, list_kind = candidates_for(reg, role, kind, free_notes)
        if free_notes:
            out["free_models"] = free_notes
        pinned = not portable
        out["reason"] = f"champion for {role}/{list_kind}"
    if not cands:
        fb = (reg.get("fallback") or {}).get(role) or {"executor": "claude", "model": None}
        cands, out["reason"] = [fb], "no candidates: fallback"
    execs = sorted({c["executor"] for c in cands} | {((reg.get("fallback") or {}).get(role) or {}).get("executor", "claude")})
    order = list(reg.get("budget", {}).get("executors", {})) + [e for e in execs if e not in reg.get("budget", {}).get("executors", {})]
    checks = {e: budget_check(reg, e) for e in order}
    out["budget"] = budget_line(reg, list(checks.values()))
    # Pooled executors (Antigravity) are judged per model: one pool can be empty while another is full.
    by_model = {}
    def check_of(c):
        e = c["executor"]
        if not checks.get(e, {}).get("pools"):
            return checks.get(e, {"state": "ok"})
        if c["model"] not in by_model:
            by_model[c["model"]] = budget_check(reg, e, model=c["model"])
        return by_model[c["model"]]
    ok = lambda c: check_of(c)["state"] == "ok"

    # explore?
    kmeta = kinds.get(kind, {})
    no_explore = []
    if urgent: no_explore.append("urgent")
    if attempt: no_explore.append("second attempt after Rework")
    if kmeta.get("allow_explore") is False: no_explore.append(f"kind {kind}")
    if fired: no_explore.append("escalation")
    if pair_experiment: no_explore.append("engineer is an experiment")
    rows = None
    chosen = None
    challengers = [c for c in cands[1:] if ok(c)]
    if not no_explore and challengers and rng.random() < float(sel.get("explore_rate", 0.2)):
        rows = load_rows(reg)
        count = lambda c: sum(1 for r in rows if r.get("role") == role and rkey(r) == ckey(c)
                              and (list_kind == "*" or r.get("task_kind") == list_kind))
        # ties (most often: none run yet) go to the newest discovered free model, so a model on a
        # short trial gets tried while it is still served
        newest = lambda c: -int(str(c.get("first_seen") or "0").replace("-", "") or 0)
        chosen = min(challengers, key=lambda c: (count(c), newest(c)))
        out["experiment"] = True
        out["reason"] = f"experiment: {ckey(chosen)} for {role}/{list_kind}"
    elif no_explore:
        out["no_explore"] = no_explore

    if chosen is None:
        champ = cands[0]
        if ok(champ):
            chosen = champ
        elif portable and not fired:
            nxt = next((c for c in cands[1:] if ok(c)), None)
            fb = (reg.get("fallback") or {}).get(role)
            if nxt is None and fb and ok(fb):
                nxt = fb
            if nxt:
                chosen = nxt
                out["reason"] = f"budget: {champ['executor']} {check_of(champ)['state']} → {ckey(nxt)}"
        if chosen is None:
            resumes = [check_of(c)["resume_at"] for c in cands if check_of(c).get("resume_at")]
            out.update(decision="wait", resume_at=min(resumes) if resumes else None,
                       reason=f"no budget for {role}/{list_kind} ({'pinned' if pinned or fired else 'all candidates held'})")
            return out

    # tester pairing: proven, preferably another model family than the engineer
    if role == "tester" and pair_with and not out["experiment"]:
        pe, pm = (pair_with.split(":", 1) + [""])[:2]
        pfam = family(reg, {"executor": pe, "model": pm})
        if family(reg, chosen) == pfam:
            rows = rows or load_rows(reg)
            board = scoreboard(reg, rows, role=role)
            m, floor = sel.get("min_samples", 5), sel.get("proven_min_rate", 0.7)
            def proven(c):
                s = board.get((role, list_kind, ckey(c))) or board.get((role, "*", ckey(c)))
                return c is cands[0] or (s and s["n_fp"] >= m and (s["first_pass"] or 0) >= floor)
            alt = next((c for c in cands if family(reg, c) != pfam and ok(c) and proven(c)), None)
            if alt:
                chosen = alt
                out["reason"] += f"; other family than engineer ({pfam})"
    out.update(decision="spawn", executor=chosen["executor"], model=chosen["model"], effort=chosen.get("effort"),
               sandbox=chosen.get("sandbox") or (reg.get("roles", {}).get(role) or {}).get("sandbox"),
               fallback=(reg.get("fallback") or {}).get(role))
    out["pick_line"] = f"{role}/{kind} · {ckey(chosen)}" + (" · EXPERIMENT" if out["experiment"] else "") + f" · {out['reason']} · {out['budget']}"
    return out


# ---------------------------------------------------------------- promotion / demotion
def decisions_append(reg, line):
    path = P(reg, "decisions")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write("# Executor decisions\n\nWritten by `fleetctl.py apply`. Veto a line by editing the user override "
                    "(executors.json next to this file) or the registry; then add a line here saying why.\n\n"
                    "| date | role/kind | change | type | numbers |\n|---|---|---|---|---|\n")
    existing = open(path).read()
    if line.split("|", 2)[2] in existing:  # same change already recorded (ignore the date)
        return False
    with open(path, "a") as f:
        f.write(line + "\n")
    return True


def apply_changes(reg, dry=False, rows=None):
    sel = reg.get("selection", {})
    m = int(sel.get("min_samples", 5))
    win, below = int(sel.get("demote_window", 5)), float(sel.get("demote_below", 0.7))
    rows = rows if rows is not None else load_rows(reg)
    board = scoreboard(reg, rows)
    today = datetime.date.today().isoformat()
    user_path = P(reg, "user_override")
    user = read_json(user_path, {}) or {}
    changes = []
    free_state = freemodels.load_state(STATE_HOME)
    for role, table in (reg.get("candidates") or {}).items():
        if not isinstance(table, dict):
            continue
        for kind, lst in table.items():
            if kind.startswith("$") or not isinstance(lst, list):
                continue
            lst = freemodels.apply_policy(reg, role, [c for c in lst if isinstance(c, dict)], free_state)[0]
            if len(lst) < 2:
                continue
            auto = (reg.get("task_kinds", {}).get(kind) or {}).get("auto_promote", True) is not False
            stat = lambda c: board.get((role, kind, ckey(c)))
            champ = lst[0]
            cs = stat(champ)
            new = None
            # promotion
            if cs and cs["n_fp"] >= 1 and cs["first_pass"] is not None:
                best = None
                for c in lst[1:]:
                    s = stat(c)
                    if not s or s["n_fp"] < m or s["first_pass"] is None:
                        continue
                    if s["first_pass"] >= cs["first_pass"] and s["mean_cost"] is not None and cs["mean_cost"] is not None \
                            and s["mean_cost"] < cs["mean_cost"]:
                        if best is None or (s["first_pass"], -s["mean_cost"]) > (stat(best)["first_pass"], -stat(best)["mean_cost"]):
                            best = c
                if best:
                    s = stat(best)
                    new = [best] + [c for c in lst if c is not best]
                    nums = f"n={s['n_fp']} fp {fmt_pct(s['first_pass'])} vs {fmt_pct(cs['first_pass'])} (n={cs['n_fp']}), cost {s['mean_cost']:.2f} vs {cs['mean_cost']:.2f}"
                    changes.append((role, kind, champ, best, "promote" if auto else "PROPOSED promote", nums, new if auto else None))
            # demotion
            if new is None and cs and len(cs["recent_fp"]) >= win:
                last = cs["recent_fp"][-win:]
                rate = sum(last) / len(last)
                if rate < below:
                    new = lst[1:2] + [champ] + lst[2:]
                    nums = f"last {win}: fp {rate * 100:.0f}% < {below * 100:.0f}%"
                    changes.append((role, kind, champ, lst[1], "demote" if auto else "PROPOSED demote", nums, new if auto else None))
    # project champions: only when a project's own runs (>= min_samples for both) disagree with the global order
    for project in sorted({r.get("project") for r in rows if r.get("project")}):
        pboard = scoreboard(reg, rows, project=project)
        for role, table in (reg.get("candidates") or {}).items():
            if not isinstance(table, dict):
                continue
            for kind, lst in table.items():
                if kind.startswith("$") or not isinstance(lst, list) or len(lst) < 2:
                    continue
                auto = (reg.get("task_kinds", {}).get(kind) or {}).get("auto_promote", True) is not False
                cs = pboard.get((role, kind, ckey(lst[0])))
                if not cs or cs["n_fp"] < m:
                    continue
                for c in lst[1:]:
                    s = pboard.get((role, kind, ckey(c)))
                    if s and s["n_fp"] >= m and s["first_pass"] > cs["first_pass"]:
                        new = [c] + [x for x in lst if x is not c]
                        nums = f"project {project}: n={s['n_fp']} fp {fmt_pct(s['first_pass'])} vs {fmt_pct(cs['first_pass'])} (n={cs['n_fp']})"
                        changes.append((role, kind, lst[0], c, ("project promote" if auto else "PROPOSED project promote"), nums,
                                        ({"project": project, "list": new} if auto else None)))
                        break
    report = []
    for role, kind, old, newc, typ, nums, new_list in changes:
        line = f"| {today} | {role}/{kind} | {ckey(old)} → {ckey(newc)} | {typ} | {nums} |"
        report.append(line)
        if dry:
            continue
        recorded = decisions_append(reg, line)
        if new_list is not None and recorded:
            if isinstance(new_list, dict):
                user.setdefault("projects", {}).setdefault(new_list["project"], {}).setdefault("candidates", {}) \
                    .setdefault(role, {})[kind] = new_list["list"]
            else:
                user.setdefault("candidates", {}).setdefault(role, {})[kind] = new_list
    if changes and not dry:
        os.makedirs(os.path.dirname(user_path), exist_ok=True)
        with open(user_path, "w") as f:
            json.dump(user, f, indent=2)
            f.write("\n")
    return report


# ---------------------------------------------------------------- seed
def seed(reg):
    have = set()
    try:
        for line in open(P(reg, "path")):
            try:
                k = legacy_identity(json.loads(line))
                if k:
                    have.add(k)
            except Exception:
                pass
    except OSError:
        pass
    added = 0
    by_project = {}
    for r in legacy_rows(reg):
        if legacy_identity(r) in have:
            continue
        append_row(reg, r)
        have.add(legacy_identity(r))
        added += 1
        by_project[r["project"]] = by_project.get(r["project"], 0) + 1
    return added, by_project


# ---------------------------------------------------------------- report
REPORT_HELP = """Window report for one project: what shipped and what it cost.

  Done          tickets with a row outcome=done. The PM writes it when a ticket reaches Done:
                  fleet log add --ticket X --role pm --executor claude --model <pm model> \\
                      --outcome done --set client_visible=true|false
                client_visible=true: the client can see the change (UI, copy, a report they read).
                false: tests, infra, refactors, internal tooling. These pm rows are markers, not
                sessions, so they are left out of the session and token totals.
  Approved      tickets with a tester row outcome=verify_pass.
  Sessions      every other spawn row, by role/executor/model: count, tokens, hours (duration_ms).
                Claude tokens are `tokens`: the size of the agent's LAST call, not what it spent
                (`cost` reads the real spend from the sessions). Codex shows output_tokens and input_tokens apart:
                input is mostly cache reads (cached_input_tokens), so it is not comparable.
  Per ticket    all session tokens in the window divided by Done (or Approved) tickets, Claude and
                Codex separately. Work on tickets not yet Done is in the numerator too.
  First pass    the first tester verdict per ticket in the window: verify_pass vs verify_fail.
  Rework        rework rounds per ticket = tester verify_fail verdicts in the window (top 5).
"""

COST_HELP = """What tickets really cost and how long they took, read from the sessions themselves.

  Spend         every Claude call in the repo's Claude Code sessions (the PM's own and its
                agents'), priced with the registry's `prices` block: API list prices, to compare
                options. Plans bill differently. Models with no price show tokens only.
  Lanes         usage from each lane row's result (Codex, opencode, claude-ollama).
  Tickets       an agent belongs to the tickets named in its spawn description, else in the
                first lines of its brief. Its role comes from the agent type and the description
                ('<role> <TICKET>', `core/pm/skills/spawn.md` §3).
  Merged        the ticket's first PR merged into trunk after its first spawn (GitHub, `gh`).
  Cycle         first spawn to merge. 'agents working' is the time any of its sessions ran.
  --ticket T    one ticket's sessions in order, with cost, calls and outcome.
  --backfill    adds a usage row for each Claude spawn row that has none, so the scoreboard
                compares Claude and lanes on the same tokens.
Session summaries are cached in {state_home}/cost-cache by file size and time.
"""


def parse_ts(s):
    if not s:
        return None
    try:
        d = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.astimezone()
    return d


def tok_parts(r):
    """(total, input, cached, output) for a row; None where unknown."""
    tok = r.get("tokens")
    if isinstance(tok, dict):
        f = usage_fields(tok)
        return f.get("tokens"), f.get("input_tokens"), f.get("cached_input_tokens"), f.get("output_tokens")
    return (tok if isinstance(tok, (int, float)) else None, r.get("input_tokens"),
            r.get("cached_input_tokens"), r.get("output_tokens"))


def report(reg, project, since, until=None):
    t0, t1 = parse_ts(since), parse_ts(until) if until else None
    if t0 is None:
        raise SystemExit(f"fleetctl: --since {since!r} is not an ISO time")
    rows = []
    for r in load_rows(reg):
        if r.get("type", "spawn") != "spawn" or (project and r.get("project") != project):
            continue
        t = parse_ts(r.get("ts"))
        if t is None or t < t0 or (t1 and t >= t1):
            continue
        rows.append(r)
    rows.sort(key=lambda r: r.get("ts") or "")
    is_marker = lambda r: r.get("role") == "pm" and r.get("outcome") in MARKER_OUTCOMES
    done = {}
    for r in rows:
        if r.get("outcome") == "done":
            done[r.get("ticket")] = r  # latest done row per ticket wins
    approved = sorted({r.get("ticket") for r in rows if r.get("role") in ("tester", "verifier-legacy")
                       and r.get("outcome") == "verify_pass"})
    sessions = [r for r in rows if not is_marker(r) and r.get("outcome") not in ("deferred", *START_OUTCOMES)]
    L = []
    w = f"{since}" + (f" to {until}" if until else " to now")
    L.append(f"Fleet report · {project or 'all projects'} · {w}")
    L.append("")
    L.append(f"Done: {len(done)}  " + ", ".join(sorted(t for t in done if t)))
    L.append(f"Approved: {len(approved)}  " + ", ".join(t for t in approved if t))
    L.append("")
    # sessions by role/executor/model
    groups = {}
    for r in sessions:
        model = (r.get("model") or "?") + (f"@{r['effort']}" if r.get("effort") else "")
        groups.setdefault((r.get("role") or "?", r.get("executor") or "claude", model), []).append(r)
    L.append(f"{'role':<12}{'executor:model':<24}{'n':>4}{'w/tok':>6}{'tokens':>12}{'input':>13}{'output':>11}{'hours':>7}")
    tot = {"claude": [0, 0.0], "codex_in": 0, "codex_cached": 0, "codex_out": 0, "codex_h": 0.0, "other": 0}
    for key in sorted(groups):
        rs = groups[key]
        role, exe, model = key
        total = inp = out = cached = 0
        ntok = 0
        hours = sum(r["duration_ms"] for r in rs if isinstance(r.get("duration_ms"), (int, float))) / 3.6e6
        for r in rs:
            t, i, c, o = tok_parts(r)
            if t is None and i is None and o is None:
                continue
            ntok += 1
            total += t or 0; inp += i or 0; out += o or 0; cached += c or 0
        if exe == "claude":
            tot["claude"][0] += total; tot["claude"][1] += hours
            cols = f"{total:>12,}{'':>13}{'':>11}"
        elif exe == "codex":
            tot["codex_in"] += inp; tot["codex_out"] += out; tot["codex_cached"] += cached; tot["codex_h"] += hours
            cols = f"{'':>12}{inp:>13,}{out:>11,}"
        else:
            tot["other"] += total
            cols = f"{total:>12,}{inp or '':>13}{out or '':>11}"
        L.append(f"{role:<12}{exe + ':' + model:<24}{len(rs):>4}{ntok:>6}{cols}{hours:>7.1f}")
    L.append(f"{'total':<12}{'':<24}{len(sessions):>4}{'':>6}{tot['claude'][0]:>12,}{tot['codex_in']:>13,}{tot['codex_out']:>11,}"
             f"{tot['claude'][1] + tot['codex_h']:>7.1f}")
    missing = sum(1 for r in sessions if tok_parts(r)[0] is None and tok_parts(r)[3] is None)
    if missing:
        L.append(f"  {missing} of {len(sessions)} sessions have no token numbers (w/tok counts the ones that do).")
    if tot["codex_in"]:
        L.append(f"  Codex input is mostly cache reads: {tot['codex_cached']:,} of {tot['codex_in']:,} "
                 f"({tot['codex_cached'] / tot['codex_in'] * 100:.0f}%) cached.")
    L.append("")
    per = lambda n, d: f"{n / d:,.0f}" if d else "—"
    nd, na = len(done), len(approved)
    L.append(f"Tokens per Done ticket ({nd}):     Claude {per(tot['claude'][0], nd)} · Codex output {per(tot['codex_out'], nd)}, input {per(tot['codex_in'], nd)}")
    L.append(f"Tokens per approved ticket ({na}): Claude {per(tot['claude'][0], na)} · Codex output {per(tot['codex_out'], na)}, input {per(tot['codex_in'], na)}")
    # first-pass approval
    first = {}
    fails = {}
    for r in rows:
        if r.get("role") in ("tester", "verifier-legacy") and r.get("outcome") in ("verify_pass", "verify_fail"):
            first.setdefault(r.get("ticket"), r.get("outcome"))
            if r.get("outcome") == "verify_fail":
                fails[r.get("ticket")] = fails.get(r.get("ticket"), 0) + 1
    if first:
        p = sum(1 for v in first.values() if v == "verify_pass")
        L.append(f"First-pass approval: {p}/{len(first)} = {p / len(first) * 100:.0f}% (first tester verdict per ticket)")
    else:
        L.append("First-pass approval: — (no tester verdicts)")
    top = sorted(fails.items(), key=lambda kv: (-kv[1], kv[0] or ""))[:5]
    L.append("Rework rounds (top 5): " + (", ".join(f"{t} {n}" for t, n in top) if top else "none"))
    if done:
        vis = [t for t, r in done.items() if r.get("client_visible") is True]
        known = [t for t, r in done.items() if isinstance(r.get("client_visible"), bool)]
        L.append(f"Client-visible Done: {len(vis)}/{len(done)} = {len(vis) / len(done) * 100:.0f}%"
                 + (f" ({len(done) - len(known)} Done rows without client_visible)" if len(known) < len(done) else ""))
    else:
        L.append("Client-visible Done: — (no Done rows)")
    return "\n".join(L)


# ---------------------------------------------------------------- selftest
def selftest():
    """log add with --set, bare k=v and --from-result writes typed values that read back."""
    import tempfile
    global STATE_HOME
    d = tempfile.mkdtemp(prefix="fleetctl-selftest-")
    old_home, old_env = STATE_HOME, os.environ.get("PLANE_FLEET_HOME")
    STATE_HOME = d
    os.environ["PLANE_FLEET_HOME"] = d
    ok = True
    def check(name, got, want):
        nonlocal ok
        good = got == want and type(got) is type(want)
        ok &= good
        print(f"{'ok  ' if good else 'FAIL'} {name}: {got!r}" + ("" if good else f" (want {want!r})"))
    try:
        base = ["log", "add", "--project", "st", "--ticket", "ST-1", "--role", "engineer", "--executor", "claude",
                "--model", "opus", "--outcome", "pr_opened"]
        main(base + ["--set", "duration_ms=1,234", "tokens=5678", "client_visible=true", "note=hello world"], quiet=True)
        main(base[:5] + ["ST-2"] + base[6:] + ["--reason", "a=b", "duration_ms=10", "tokens=20"], quiet=True)
        res = os.path.join(d, "result.json")
        json.dump({"executor": "codex", "model": "gpt-x", "effort": "high", "role": "tester", "ticket": "ST-3", "status": "completed",
                   "durationMs": 90000, "usage": {"input_tokens": 1000, "cached_input_tokens": 900, "output_tokens": 50}},
                  open(res, "w"))
        main(["log", "add", "--project", "st", "--outcome", "verify_pass", "--from-result", res], quiet=True)
        reg = load_registry(None, "st")
        reg.setdefault("log", {})["path"] = os.path.join(d, "executor-outcomes.jsonl")
        rows = {r["ticket"]: r for r in load_rows(reg)}
        r1, r2, r3 = rows.get("ST-1", {}), rows.get("ST-2", {}), rows.get("ST-3", {})
        check("--set duration_ms", r1.get("duration_ms"), 1234)
        check("--set tokens", r1.get("tokens"), 5678)
        check("--set client_visible", r1.get("client_visible"), True)
        check("--set string", r1.get("note"), "hello world")
        check("bare duration_ms", r2.get("duration_ms"), 10)
        check("bare tokens", r2.get("tokens"), 20)
        try:
            import contextlib, io
            with contextlib.redirect_stderr(io.StringIO()):
                main(base[:5] + ["ST-B"] + base[6:-1] + ["blocked"], quiet=True)
            refused = False
        except SystemExit:
            refused = True
        check("log add: blocked with no reason is refused", refused, True)
        bres = os.path.join(d, "blocked.json")
        json.dump({"executor": "codex", "model": "gpt-x", "role": "engineer", "ticket": "ST-C", "status": "completed",
                   "lastMessage": "Done what I could.\nBlocked: the migration needs a DBA decision"}, open(bres, "w"))
        main(["log", "add", "--project", "st", "--outcome", "blocked", "--from-result", bres], quiet=True)
        rc = {r["ticket"]: r for r in load_rows(reg)}.get("ST-C", {})
        check("log add: a blocked lane takes its reason from the lane", rc.get("reason"), "lane said: Blocked: the migration needs a DBA decision")
        dec = ["log", "add", "--project", "st", "--ticket", "RUN", "--role", "pm", "--executor", "claude", "--model", "opus",
               "--outcome", "decision"]
        check("log add: two decisions in a minute both log",
              (main(dec + ["--reason", "engineers to codex: owner order"], quiet=True), main(dec + ["--reason", "testers to codex"], quiet=True)), (0, 0))
        check("a decision is not scored", any(k[0] == "pm" for k in scoreboard(reg, load_rows(reg))), False)
        check("--reason kept", r2.get("reason"), "a=b")
        check("row shape", sorted(k for k in r2 if k != "quality")[:6], ["duration_ms", "executor", "experiment", "model", "outcome", "project"])
        check("from-result executor", r3.get("executor"), "codex")
        check("from-result role", r3.get("role"), "tester")
        check("from-result duration_ms", r3.get("duration_ms"), 90000)
        check("from-result output_tokens", r3.get("output_tokens"), 50)
        check("from-result input_tokens", r3.get("input_tokens"), 1000)
        check("from-result tokens", r3.get("tokens"), 1050)
        check("from-result effort", r3.get("effort"), "high")
        check("no effort, no key", "effort" in r1, False)
        board = scoreboard(reg, list(rows.values()), role="tester")
        check("scoreboard keys effort", ("tester", "*", "codex:gpt-x@high") in board, True)
        for folder in ("-old-path-repo", "-new-path-repo"):  # one legacy row, seeded from two folders
            append_row(reg, {"type": "spawn", "ts": "2026-09-01T00:00:00Z", "project": "st", "ticket": "ST-9",
                             "role": "engineer", "executor": "claude", "model": "sonnet", "outcome": "pr_opened",
                             "source_key": f"{folder}/fleet-model-runs.jsonl|2026-09-01T00:00:00Z|ST-9|worker"})
        check("a moved repo's legacy row counts once", sum(1 for r in load_rows(reg) if r.get("ticket") == "ST-9"), 1)
        import contextlib, io
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                main(base[:5] + ["ST-4"] + base[6:-1] + ["verify_fail"], quiet=True)
            check("verify_fail without a cause is refused", "logged", "refused")
        except SystemExit:
            check("verify_fail without a cause is refused", True, True)
        main(base[:5] + ["ST-4"] + base[6:-1] + ["verify_fail", "--cause", "ticket", "--reason", "AC 2 fails"], quiet=True)
        r4 = {r["ticket"]: r for r in load_rows(reg)}.get("ST-4", {})
        check("--cause stored", r4.get("fail_cause"), "ticket")
        st4 = base[:5] + ["ST-4"] + base[6:-1] + ["verify_fail", "--cause", "ticket", "--reason", "AC 2 fails"]
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = main(st4, quiet=True)
        check("log add: a repeat within 10 minutes is refused", (code, "repeats a row" in err.getvalue()), (5, True))
        check("log add: --force logs it anyway", main(st4 + ["--force"], quiet=True), 0)
        check("log add: another executor is not a repeat",
              main(base[:5] + ["ST-4"] + base[6:7] + ["codex"] + base[8:-1] + ["verify_fail", "--cause", "ticket", "--reason", "AC 2 fails"], quiet=True), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                main(base[:5] + ["ST-6"] + base[6:-1] + ["verify_fail", "--cause", "missed"], quiet=True)
                vf_refused = False
            except SystemExit:
                vf_refused = True
        check("verify_fail without a reason is refused", vf_refused, True)
        main(base[:5] + ["ST-6"] + base[6:-1] + ["verify_fail", "--cause", "missed", "--defect", "other_path",
                                                 "--reason", "edit path skips the hold"], quiet=True)
        check("--defect stored", {r["ticket"]: r for r in load_rows(reg)}.get("ST-6", {}).get("defect"), "other_path")
        selftest_214(check, d, reg, base)
        main(base[:5] + ["ST-5"] + base[6:] + ["--set", "agent_id=a77"], quiet=True)
        with contextlib.redirect_stderr(io.StringIO()):
            code = main(base[:5] + ["ST-6"] + base[6:] + ["--set", "agent_id=a77"], quiet=True)
        check("log add: the same agent_id and outcome is refused", code, 5)
        fix = ["log", "add", "--project", "st", "--ticket", "ST-1", "--role", "pm", "--executor", "claude", "--model", "opus",
               "--outcome", "retro_fix"]
        check("log add: two retro fixes in a row both log", (main(fix + ["--reason", "a"], quiet=True), main(fix + ["--reason", "b"], quiet=True)), (0, 0))
        check("retro_fix is not scored", any(k[0] == "pm" for k in scoreboard(reg, load_rows(reg))), False)
        pools = {"gemini": ["g-wk"], "gemini-4-argon": ["argon-wk"], "claude": ["3p-wk", "3p-5h"]}
        check("pool: longest prefix", pool_of({"pools": pools}, "gemini-4-argon"), "gemini-4-argon")
        check("pool: plain prefix", pool_of({"pools": pools}, "gemini-3.8-flash"), "gemini")
        check("pool: unknown model", pool_of({"pools": pools}, "kimi-k3"), None)
        t = 1_000_000.0
        check("judge: hard stop", judge(96, t + 60, 300 * 60, 95, 20, t)[0], "stop")
        check("judge: ahead of pace", judge(50, t + 290 * 60, 300 * 60, 95, 20, t)[0], "hold")
        check("judge: on pace", judge(30, t + 150 * 60, 300 * 60, 95, 20, t)[0], "ok")
        reg = load_registry(None, "st")
        st_path = state_path(reg, "antigravity")
        json.dump({"usage": {"at": time.time(), "buckets": {"3p-wk": [10, t + 9e6, 10080], "3p-5h": [97, time.time() + 600, 300],
                                                             "g-wk": [5, time.time() + 9e6, 10080]}}}, open(st_path, "w"))
        reg.setdefault("budget", {}).setdefault("executors", {})["antigravity"] = {"source": "antigravity-usage", "pools": pools}
        check("antigravity: a full pool stops its model", budget_check(reg, "antigravity", model="claude-opus-5-5")["state"], "stop")
        check("antigravity: other pools still run", budget_check(reg, "antigravity", model="gemini-3.8-flash")["state"], "ok")
        import fleetcost
        fleetcost.selftest(check)
        import fleetretro
        fleetretro.selftest(check, sys.modules[__name__])
        import fleetreview
        fleetreview.selftest(check)
        import fleetfindings
        fleetfindings.selftest(check)
        freemodels.selftest(check)
        import fleetstatus
        fleetstatus.selftest(check)
        import fleetres
        fleetres.selftest(check)
        import fleetcache
        fleetcache.selftest(check)
        import fleettemplate
        fleettemplate.selftest(check)
        import fleetgate
        fleetgate.selftest(check)
        import fleetintake
        fleetintake.selftest(check)
        selftest_300(check)
        import fleetschedule
        fleetschedule.selftest(check)
        guard = os.path.join(FLEET_ROOT, "..", "..", "hooks", "unattended-guard.py")
        if os.path.exists(guard):
            g = subprocess.run([sys.executable, guard, "--selftest"], capture_output=True, text=True)
            check("unattended guard selftest", (g.returncode, [l for l in g.stdout.splitlines() if l.startswith("FAIL")]), (0, []))
        w = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fleetwatch.py"), "--selftest"],
                           capture_output=True, text=True, env={**os.environ, "PLANE_FLEET_HOME": tempfile.mkdtemp()})
        check("watch: fleetwatch selftest", (w.returncode, [l for l in w.stdout.splitlines() if l.startswith("FAIL")]), (0, []))
    finally:
        STATE_HOME = old_home
        if old_env is None:
            os.environ.pop("PLANE_FLEET_HOME", None)
        else:
            os.environ["PLANE_FLEET_HOME"] = old_env
    print("selftest passed" if ok else "selftest FAILED")
    return 0 if ok else 1


# ---------------------------------------------------------------- rounds, queue, questions (2.14)
# 2026-11, one 20 hour run: 22 of 38 tickets failed their first test and one ticket had 10
# rework sessions. The PM skill already said "cap at two reworks" and was passed under load, so
# the cap now lives here and the usage-pacer hook enforces it. Five spawns the machine gate
# refused were retried by hand: the queue parks them. Approved PRs waited 12 hours on owner
# answers nobody tracked: the questions file keeps them in front of the PM.
TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
# Prefixes that look like ticket ids and never are (UTF-8, SHA-256, ISO-8601).
NOT_TICKETS = ("UTF", "SHA", "ISO", "RFC", "HTTP", "TLS", "ES", "MD", "AES", "RSA")
TEST_ROUNDS_MAX = 2
QUEUE_ROLES = ("engineer", "tester")


def ticket_in(text):
    """The first ticket identifier in a prompt, or None."""
    for m in TICKET_RE.finditer(text or ""):
        if m.group(0).split("-", 1)[0] not in NOT_TICKETS:
            return m.group(0)
    return None


def yes_no(v):
    """yes/no, true/false or a bool -> bool; anything else -> None."""
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    return True if s in ("yes", "y", "true") else False if s in ("no", "n", "false") else None


def failed_rounds(rows, ticket, project=None):
    """Failed test rounds of one ticket: its verify_fail rows, a fail written twice counted once.
    Two fail rows are one round when they share an agent_id, or when no engineer row of the
    ticket sits between them and they are at most DUPLICATE_WINDOW_S apart."""
    n, last, agents, eng_since = 0, None, set(), True
    for r in sorted(rows, key=lambda r: r.get("ts") or ""):
        if r.get("ticket") != ticket or r.get("usage_only") or r.get("type", "spawn") != "spawn":
            continue
        if project and r.get("project") and r.get("project") != project:
            continue
        if r.get("outcome") != "verify_fail":
            eng_since = eng_since or r.get("role") == "engineer"
            continue
        aid = r.get("agent_id")
        if aid and aid in agents:
            continue
        if aid:
            agents.add(aid)
        t = parse_ts(r.get("ts"))
        if not eng_since and last is not None and t is not None and 0 <= (t - last).total_seconds() <= DUPLICATE_WINDOW_S:
            continue
        n, last, eng_since = n + 1, t, False
    return n


def state_file(kind, project):
    """<PLANE_FLEET_HOME>/<kind>-<project>.jsonl: the queue, questions and round allowances."""
    return os.path.join(STATE_HOME, f"{kind}-{project or 'default'}.jsonl")


def read_jsonl(path):
    out = []
    try:
        for line in open(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict):
                out.append(r)
    except OSError:
        pass
    return out


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def add_jsonl(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def next_id(rows, prefix):
    nums = [int(m.group(1)) for m in (re.match(rf"{prefix}(\d+)$", str(r.get("id") or "")) for r in rows) if m]
    return f"{prefix}{max(nums, default=0) + 1}"


def find_id(rows, given, prefix):
    want = str(given).strip()
    want = want if want.startswith(prefix) else prefix + want
    return next((r for r in rows if str(r.get("id")) == want), None)


def age_text(ts, now=None):
    t = parse_ts(ts)
    if t is None:
        return "?"
    s = max(0, (now or time.time()) - t.timestamp())
    return f"{s / 3600:.1f}h" if s >= 3600 else f"{s / 60:.0f}m"


def rounds_cap(cwd):
    """fleet.test_rounds_max from the project config (default 2); 0 turns the cap off."""
    try:
        v = (project_config(cwd or os.getcwd()).get("fleet") or {}).get("test_rounds_max", TEST_ROUNDS_MAX)
        return int(v) if v is not None else TEST_ROUNDS_MAX
    except Exception:
        return TEST_ROUNDS_MAX


def round_state(rows, ticket, project, cap):
    """Rounds, cap and whether one more rework spawn may start. Under the cap it may. At or past
    it, it needs an owner allowance that is unused, or one already used at this same round count
    (a respawn of the same round, after a crash or a refused spawn, needs no second allowance)."""
    n = failed_rounds(rows, ticket, project)
    allows = [a for a in read_jsonl(state_file("rounds-allow", project)) if a.get("ticket") == ticket]
    st = {"ticket": ticket, "project": project, "rounds": n, "cap": cap, "allowances": len(allows),
          "unused": sum(1 for a in allows if not a.get("used"))}
    if cap <= 0 or n < cap:
        st.update(allowed=True, needs_allowance=False)
    else:
        same = any(a.get("used") and a.get("used_at_rounds") == n for a in allows)
        st.update(allowed=bool(same or st["unused"]), needs_allowance=not same)
    return st


def consume_allowance(project, ticket, rounds):
    """Mark one owner allowance used for this round count. Returns its id, or None."""
    path = state_file("rounds-allow", project)
    allows = read_jsonl(path)
    if any(a.get("ticket") == ticket and a.get("used") and a.get("used_at_rounds") == rounds for a in allows):
        return None
    for a in allows:
        if a.get("ticket") == ticket and not a.get("used"):
            a.update(used=True, used_ts=now_iso(), used_at_rounds=rounds)
            write_jsonl(path, allows)
            return a.get("id")
    return None


def rework_refusal(st):
    t = st["ticket"]
    return (f"rework cap: {t} has {st['rounds']} failed test rounds (cap {st['cap']}, fleet.test_rounds_max). Do not start "
            f"another rework session. Write the rework ledger entry, put the three options to the owner (narrow the ticket, "
            f"split the leftovers into a follow-up, go on). When the owner allows one more round, record it with: "
            f"fleet rounds allow {t} --reason \"<the owner's words>\". Off switch, on the owner's word only: "
            f"touch {STATE_HOME}/rework-cap-off.")


def rework_gate(cwd, text):
    """For the usage-pacer hook: the round state of the first ticket in an engineer prompt, or
    None when there is no ticket, the cap is off, or the switch file rework-cap-off exists."""
    if os.path.exists(os.path.join(STATE_HOME, "rework-cap-off")):
        return None
    ticket = ticket_in(text)
    if not ticket:
        return None
    cap = rounds_cap(cwd)
    if cap <= 0:
        return None
    reg = load_registry(cwd)
    return round_state(load_rows(reg), ticket, reg.get("_project"), cap)


def heavy_admitted(cwd):
    """(may a heavy session start now, one line why). No probe or the resources-off switch: yes."""
    if os.path.exists(os.path.join(STATE_HOME, "resources-off")):
        return True, "resources-off switch"
    try:
        import fleetres
        cfg, paths, wdirs = fleetres.context(cwd or os.getcwd())
        sample = fleetres.probe(paths, top_n=8)
        gate = fleetres.judge(sample, cfg, wdirs)
        return bool(fleetres.admit(gate, True)), fleetres.summary_line(sample, gate)
    except Exception as e:
        return True, f"no machine probe ({type(e).__name__})"


def queue_line(r):
    return (f"{r.get('id')} {r.get('ticket')} {r.get('role')} slot {r.get('slot')} brief {r.get('brief')} "
            f"queued {age_text(r.get('ts'))} ago" + (f", popped {r.get('popped_ts')}" if r.get("popped") else ""))


def question_line(r):
    return (f"{r.get('id')} {r.get('ticket')}" + (f" PR #{r['pr']}" if r.get("pr") else "") + f" open {age_text(r.get('ts'))}: "
            + str(r.get("text") or "") + (f" -> answered: {r.get('answer')}" if r.get("closed") else ""))


def run_rounds(args, reg, ap):
    project = args.project or reg.get("_project")
    cwd = args.cwd or os.getcwd()
    cap = rounds_cap(cwd)
    if args.action == "allow":
        ticket = (args.target or args.ticket or "").strip().upper()
        if not TICKET_RE.fullmatch(ticket):
            ap.error("rounds allow needs a ticket id: fleet rounds allow <TICKET> --reason \"<the owner's words>\"")
        if not (args.reason or "").strip():
            ap.error("rounds allow needs --reason: the owner's words, as said")
        path = state_file("rounds-allow", project)
        rows = read_jsonl(path)
        row = {"id": next_id(rows, "a"), "ts": now_iso(), "project": project, "ticket": ticket,
               "reason": args.reason.strip(), "used": False}
        add_jsonl(path, row)
        st = round_state(load_rows(reg), ticket, project, cap)
        print(f"allowed one more rework round for {ticket} ({row['id']}): {st['rounds']} failed rounds, cap {cap}. "
              "The next engineer spawn for it uses this allowance.")
        return 0
    ticket = args.ticket or (args.action if args.action and TICKET_RE.fullmatch(args.action) else None)
    if args.action and not ticket:
        ap.error(f"unknown rounds action {args.action!r}: use `fleet rounds [--ticket T]` or `fleet rounds allow <T> --reason ...`")
    rows = load_rows(reg)
    tickets = [ticket] if ticket else sorted({r.get("ticket") for r in rows if r.get("outcome") == "verify_fail" and r.get("ticket")
                                              and (not project or not r.get("project") or r.get("project") == project)})
    states = [round_state(rows, t, project, cap) for t in tickets]
    states = [s for s in states if s["rounds"] or ticket]
    states.sort(key=lambda s: (-s["rounds"], s["ticket"]))
    if args.json:
        print(json.dumps(states, indent=2))
        return 0
    if not states:
        print(f"no failed test rounds logged · cap {cap}" + (" (off)" if cap <= 0 else ""))
        return 0
    for s in states:
        at = s["cap"] > 0 and s["rounds"] >= s["cap"]
        more = "one more round allowed" if s["allowed"] else "AT CAP: one more round needs the owner (`fleet rounds allow`)"
        print(f"{s['ticket']}: {s['rounds']} failed test round{'s' if s['rounds'] != 1 else ''}, cap "
              f"{s['cap'] if s['cap'] > 0 else 'off'} · {more}" + (f" · {s['unused']} unused allowance" if at and s["unused"] else ""))
    return 0


def run_queue(args, reg, ap):
    project = args.project or reg.get("_project")
    path = state_file("queue", project)
    rows = read_jsonl(path)
    if args.action == "add":
        if not (args.ticket and args.role and args.slot and args.brief):
            ap.error("queue add needs --ticket, --role engineer|tester, --slot and --brief <file>")
        brief = os.path.abspath(X(args.brief))
        if not os.path.isfile(brief):
            ap.error(f"queue add: brief file {brief} not found; save the brief to a file first")
        row = {"id": next_id(rows, "s"), "ts": now_iso(), "project": project, "ticket": args.ticket, "role": args.role,
               "slot": str(args.slot), "brief": brief, "popped": False}
        add_jsonl(path, row)
        print(f"queued {row['id']} {args.ticket} {args.role} slot {row['slot']}. Send it when `fleet queue next` prints it.")
        return 0
    waiting = sorted((r for r in rows if not r.get("popped")), key=lambda r: r.get("ts") or "")
    if args.action == "list":
        shown = sorted(rows, key=lambda r: r.get("ts") or "") if args.all else waiting
        if args.json:
            print(json.dumps(shown, indent=2))
        elif not shown:
            print("queue empty")
        else:
            print("\n".join(queue_line(r) for r in shown))
        return 0
    if not waiting:
        print("queue empty")
        return 4
    ok, why = heavy_admitted(args.cwd or os.getcwd())
    head = waiting[0]
    if not ok:
        print(f"held: the machine gate admits no heavy session now ({why}). {len(waiting)} queued, oldest "
              f"{head.get('id')} {head.get('ticket')} waiting {age_text(head.get('ts'))}.")
        return 3
    if args.pop:
        for r in rows:
            if r.get("id") == head.get("id"):
                r.update(popped=True, popped_ts=now_iso())
                head = r
        write_jsonl(path, rows)
    print(json.dumps(head) if args.json else queue_line(head))
    return 0


def run_questions(args, reg, ap):
    project = args.project or reg.get("_project")
    path = state_file("questions", project)
    rows = read_jsonl(path)
    if args.action == "add":
        if not (args.ticket and (args.text or "").strip()):
            ap.error("questions add needs --ticket and --text")
        row = {"id": next_id(rows, "q"), "ts": now_iso(), "project": project, "ticket": args.ticket,
               **({"pr": args.pr} if args.pr else {}), "text": args.text.strip(), "closed": False}
        add_jsonl(path, row)
        print(f"question {row['id']} open on {args.ticket}" + (f" PR #{args.pr}" if args.pr else ""))
        return 0
    if args.action == "close":
        if not args.target or not (args.answer or "").strip():
            ap.error("questions close needs the id and --answer \"...\"")
        q = find_id(rows, args.target, "q")
        if q is None:
            ap.error(f"no question {args.target}")
        q.update(closed=True, closed_ts=now_iso(), answer=args.answer.strip())
        write_jsonl(path, rows)
        print(f"closed {q['id']} on {q.get('ticket')} after {age_text(q.get('ts'))}")
        return 0
    shown = sorted((r for r in rows if args.all or not r.get("closed")), key=lambda r: r.get("ts") or "")
    if args.json:
        print(json.dumps(shown, indent=2))
    elif not shown:
        print("no open owner questions")
    else:
        print("\n".join(question_line(r) for r in shown))
    return 0


def selftest_300(check):
    """Only a fail the tester put on the model ("missed") scores against an engineer (3.0.0)."""
    def rows(cause):
        return [{"project": "st", "ticket": "ST-90", "role": "engineer", "outcome": "pr_opened", "ts": "2026-11-01T00:00:00Z"},
                {"project": "st", "ticket": "ST-90", "role": "tester", "outcome": "verify_fail", "ts": "2026-11-01T01:00:00Z",
                 **({"fail_cause": cause} if cause else {})}]
    for cause, want in (("missed", False), ("ticket", None), ("environment", None), ("spec_changed", None),
                        ("pm_ruling", None), (None, False)):
        rs = rows(cause)
        derive_quality(rs)
        check(f"engineer quality after a verify_fail with cause {cause}", rs[0]["quality"], want)
    own = [{"project": "st", "ticket": "ST-91", "role": "engineer", "outcome": "verify_fail",
            "verify_first_pass": False, "fail_cause": "environment"}]
    derive_quality(own)
    check("an engineer row failed for the environment is not scored", own[0]["quality"], None)
    sel = (read_json(os.path.join(HERE, "..", "references", "executors.json"), {}) or {}).get("selection", {})
    check("demote_window is 20", sel.get("demote_window"), 20)


def selftest_214(check, d, reg, base):
    """2.14: spawn rows, pm_ruling and the finding fields, rounds and allowances, queue, questions."""
    import contextlib, io
    q = lambda argv: main(argv, quiet=True)
    out = io.StringIO()
    sp = base[:5] + ["ST-20"] + base[6:-1]
    check("log add: a spawn row then its result row log without --force", (q(sp + ["spawn"]), q(sp + ["pr_opened"])), (0, 0))
    rows = load_rows(reg)
    check("a spawn row is not scored as a session",
          sum(v["n"] for k, v in scoreboard(reg, [r for r in rows if r.get("ticket") == "ST-20"]).items() if k[1] == "*"), 1)
    q(base[:5] + ["ST-21"] + base[6:-1] + ["verify_fail", "--cause", "pm_ruling", "--reason", "brief moved the rule",
                                           "--in-list", "no", "--severity", "s2", "--repeat", "yes"])
    r21 = {r["ticket"]: r for r in load_rows(reg)}.get("ST-21", {})
    check("--cause pm_ruling stored", r21.get("fail_cause"), "pm_ruling")
    check("--in-list stored as a bool", r21.get("in_list"), False)
    check("--severity stored", r21.get("severity"), "s2")
    check("--repeat stored as a bool", r21.get("repeat"), True)
    t0 = parse_ts("2026-10-01T10:00:00Z").timestamp()
    at = lambda m: datetime.datetime.fromtimestamp(t0 + m * 60, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fx = [{"ts": at(0), "ticket": "RX-1", "role": "engineer", "outcome": "pr_opened"},
          {"ts": at(30), "ticket": "RX-1", "role": "tester", "outcome": "verify_fail", "agent_id": "t1"},
          {"ts": at(31), "ticket": "RX-1", "role": "tester", "outcome": "verify_fail"},            # written twice
          {"ts": at(50), "ticket": "RX-1", "role": "engineer", "outcome": "spawn"},
          {"ts": at(80), "ticket": "RX-1", "role": "tester", "outcome": "verify_fail", "agent_id": "t2"},
          {"ts": at(200), "ticket": "RX-1", "role": "pm", "outcome": "verify_fail", "agent_id": "t2"},  # same session again
          {"ts": at(81), "ticket": "RX-2", "role": "tester", "outcome": "verify_fail"},
          {"ts": at(90), "ticket": "RX-1", "role": "tester", "outcome": "verify_fail", "project": "other"}]
    check("failed_rounds: a fail written twice counts once", failed_rounds(fx, "RX-1", "st"), 2)
    check("failed_rounds: another ticket", failed_rounds(fx, "RX-2"), 1)
    check("failed_rounds: a fail logged on the engineer row counts",
          failed_rounds([{"ts": at(1), "ticket": "RX-3", "role": "engineer", "outcome": "verify_fail"}], "RX-3"), 1)
    check("ticket_in skips UTF-8", ticket_in("read UTF-8 notes, then work RX-1 in slot 2"), "RX-1")
    check("round_state: under the cap", round_state(fx, "RX-2", "st", 2)["allowed"], True)
    check("round_state: at the cap, no allowance", round_state(fx, "RX-1", "st", 2)["allowed"], False)
    check("round_state: cap 0 is off", round_state(fx, "RX-1", "st", 0)["allowed"], True)
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            q(["rounds", "allow", "RX-1", "--project", "st"])
            refused = False
        except SystemExit:
            refused = True
    check("rounds allow without --reason is refused", refused, True)
    with contextlib.redirect_stdout(out):
        q(["rounds", "allow", "RX-1", "--project", "st", "--reason", "go on, owner"])
    st = round_state(fx, "RX-1", "st", 2)
    check("rounds allow: one more round allowed", (st["allowed"], st["needs_allowance"]), (True, True))
    consume_allowance("st", "RX-1", st["rounds"])
    check("allowance used: a respawn of the same round still passes", round_state(fx, "RX-1", "st", 2)["allowed"], True)
    fx.append({"ts": at(300), "ticket": "RX-1", "role": "tester", "outcome": "verify_fail", "agent_id": "t3"})
    check("allowance used: the next failed round needs a new one", round_state(fx, "RX-1", "st", 2)["allowed"], False)
    check("rework_refusal names the allow command", "fleet rounds allow RX-1" in rework_refusal(round_state(fx, "RX-1", "st", 2)), True)
    open(os.path.join(STATE_HOME, "rework-cap-off"), "w").close()
    check("rework-cap-off switch turns the gate off", rework_gate(d, "work RX-1"), None)
    os.remove(os.path.join(STATE_HOME, "rework-cap-off"))
    brief = os.path.join(d, "brief.md")
    open(brief, "w").write("brief")
    global heavy_admitted
    real = heavy_admitted
    try:
        with contextlib.redirect_stdout(out):
            empty = q(["queue", "next", "--project", "st"])
            q(["queue", "add", "--project", "st", "--ticket", "RX-5", "--role", "engineer", "--slot", "3", "--brief", brief])
            q(["queue", "add", "--project", "st", "--ticket", "RX-6", "--role", "tester", "--slot", "4", "--brief", brief])
            heavy_admitted = lambda cwd: (False, "CRITICAL")
            held = q(["queue", "next", "--project", "st"])
            heavy_admitted = lambda cwd: (True, "OK")
            sent = q(["queue", "next", "--project", "st", "--pop"])
        check("queue next: empty 4, held 3, admitted 0", (empty, held, sent), (4, 3, 0))
        qrows = read_jsonl(state_file("queue", "st"))
        check("queue: the oldest pops first", [(r["ticket"], r["popped"]) for r in qrows], [("RX-5", True), ("RX-6", False)])
        check("queue: rows carry id, ts, popped_ts", all(k in qrows[0] for k in ("id", "ts", "popped_ts")), True)
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                q(["queue", "add", "--project", "st", "--ticket", "RX-7", "--role", "engineer", "--slot", "1", "--brief", brief + ".none"])
                refused = False
            except SystemExit:
                refused = True
        check("queue add: a missing brief file is refused", refused, True)
    finally:
        heavy_admitted = real
    with contextlib.redirect_stdout(out):
        q(["questions", "add", "--project", "st", "--ticket", "RX-8", "--pr", "12", "--text", "ship the empty state as is?"])
        q(["questions", "add", "--project", "st", "--ticket", "RX-9", "--text", "which rounding?"])
        q(["questions", "close", "1", "--project", "st", "--answer", "yes"])
    qs = read_jsonl(state_file("questions", "st"))
    check("questions: close marks one, keeps the answer", [(r["id"], r["closed"], r.get("answer")) for r in qs],
          [("q1", True, "yes"), ("q2", False, None)])
    check("questions: pr stored as a number", qs[0].get("pr"), 12)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        q(["questions", "list", "--project", "st"])
    check("questions list shows only the open one", ("q2" in buf.getvalue(), "q1" in buf.getvalue()), (True, False))


# ---------------------------------------------------------------- project config
def project_config(cwd):
    """<repo>/.plane/config.json, deep-merged with {state_home}/projects/<repo>.json (the user's
    private values for that project win). Keeps owner and client details out of the repo."""
    top = git(cwd, "rev-parse", "--show-toplevel") or cwd
    base = read_json(os.path.join(top, ".plane", "config.json"), {}) or {}
    project = project_of(cwd)
    user = read_json(os.path.join(STATE_HOME, "projects", f"{project}.json"), {}) or {}
    cfg = deep_merge(base, user)
    cfg["_sources"] = [p for p, d in ((os.path.join(top, ".plane/config.json"), base),
                                      (os.path.join(STATE_HOME, "projects", f"{project}.json"), user)) if d]
    return cfg


# ---------------------------------------------------------------- cli
def main(argv=None, quiet=False):
    ap = argparse.ArgumentParser(prog="fleetctl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick"); p.add_argument("--role", required=True); p.add_argument("--kind")
    p.add_argument("--triggers", default=""); p.add_argument("--urgent", action="store_true")
    p.add_argument("--attempt", type=int, default=0); p.add_argument("--pair-with")
    p.add_argument("--pair-experiment", action="store_true"); p.add_argument("--cwd"); p.add_argument("--seed", type=int)
    b = sub.add_parser("budget"); b.add_argument("action", nargs="?", default="line")
    b.add_argument("executor", nargs="?"); b.add_argument("--minutes", type=float); b.add_argument("--reason", default="rate limited")
    b.add_argument("--json", action="store_true"); b.add_argument("--cwd")
    b.add_argument("--model", help="check EXE: judge this model's pool (Antigravity)")
    lg = sub.add_parser("log"); lg.add_argument("action", choices=["add", "backfill"])
    for f in ("ticket", "role", "executor", "model", "effort", "outcome", "kind", "project", "cwd", "reason"):
        lg.add_argument(f"--{f}")
    lg.add_argument("--experiment", action="store_true"); lg.add_argument("--set", nargs="*", default=None, action="extend")
    lg.add_argument("--from-result", help="a lane's result.json: duration, tokens and identity come from it")
    lg.add_argument("--cause", choices=FAIL_CAUSES, help="why the tester failed it; required with --outcome verify_fail")
    lg.add_argument("--defect", choices=DEFECTS, help="what kind of defect a missed verify_fail was (see DEFECTS)")
    lg.add_argument("--force", action="store_true", help="log it even when a matching row is already logged")
    lg.add_argument("--in-list", choices=["yes", "no"], help="verify_fail: was the finding in the case list")
    lg.add_argument("--severity", choices=SEVERITIES, help="verify_fail: s1 blocks (data, money, customer send, security, main path), s2 has a workaround, s3 polish")
    lg.add_argument("--repeat", choices=["yes", "no"], help="verify_fail: was the same finding raised in an earlier round")
    rd = sub.add_parser("rounds", description="Failed test rounds per ticket against fleet.test_rounds_max; `allow` records the owner's go-ahead for one more.")
    rd.add_argument("action", nargs="?", help="allow, or a ticket id"); rd.add_argument("target", nargs="?", help="allow: the ticket")
    rd.add_argument("--ticket"); rd.add_argument("--reason", help="allow: the owner's words"); rd.add_argument("--cwd")
    rd.add_argument("--project"); rd.add_argument("--json", action="store_true")
    qu = sub.add_parser("queue", description="Spawns the machine gate refused, parked until it admits a heavy session.")
    qu.add_argument("action", choices=["add", "list", "next"]); qu.add_argument("--ticket"); qu.add_argument("--role", choices=QUEUE_ROLES)
    qu.add_argument("--slot"); qu.add_argument("--brief", help="add: the saved brief file"); qu.add_argument("--pop", action="store_true")
    qu.add_argument("--all", action="store_true"); qu.add_argument("--cwd"); qu.add_argument("--project"); qu.add_argument("--json", action="store_true")
    qs = sub.add_parser("questions", description="Open owner decisions, the PR each one holds, and their age.")
    qs.add_argument("action", nargs="?", default="list", choices=["add", "list", "close"]); qs.add_argument("target", nargs="?", help="close: the id")
    qs.add_argument("--ticket"); qs.add_argument("--pr", type=int); qs.add_argument("--text"); qs.add_argument("--answer")
    qs.add_argument("--all", action="store_true"); qs.add_argument("--cwd"); qs.add_argument("--project"); qs.add_argument("--json", action="store_true")
    co = sub.add_parser("cost", description=COST_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    co.add_argument("--cwd"); co.add_argument("--project"); co.add_argument("--since"); co.add_argument("--until")
    co.add_argument("--ticket"); co.add_argument("--json", action="store_true")
    co.add_argument("--backfill", action="store_true", help="write the real usage onto the log's Claude spawn rows")
    co.add_argument("--dry-run", action="store_true", help="with --backfill: show what would be written")
    co.add_argument("--claude-dir", help="Claude Code projects folder (default $CLAUDE_CONFIG_DIR/projects or ~/.claude/projects)")
    rt = sub.add_parser("retro", description="The fleet reviews itself: rounds, spend, tool calls and findings (fleetretro.py).")
    rt.add_argument("--cwd"); rt.add_argument("--project"); rt.add_argument("--since"); rt.add_argument("--until")
    rt.add_argument("--hours", type=float); rt.add_argument("--json", action="store_true")
    rt.add_argument("--no-record", action="store_true", help="don't save this run's findings for repeat detection")
    rt.add_argument("--claude-dir", help="Claude Code projects folder (default $CLAUDE_CONFIG_DIR/projects or ~/.claude/projects)")
    rv = sub.add_parser("review", description="Every run measured the same way, kept, and compared with the runs before (fleetreview.py).")
    rv.add_argument("--cwd"); rv.add_argument("--project"); rv.add_argument("--since", help="look for runs from here (default: after the last kept run, else 30 days)")
    rv.add_argument("--last", type=int, help="runs to show side by side (default fleet.review.compare_runs, 5)")
    rv.add_argument("--gap-hours", type=float, help="a gap longer than this between log rows starts a new run (default 4)")
    rv.add_argument("--json", action="store_true"); rv.add_argument("--md", help="also write the review as markdown to this file")
    rv.add_argument("--no-record", action="store_true", help="measure and show, keep nothing")
    rv.add_argument("--rebuild", action="store_true", help="measure every run since --since again and rewrite the history")
    rv.add_argument("--claude-dir", help="Claude Code projects folder (default $CLAUDE_CONFIG_DIR/projects or ~/.claude/projects)")
    rp = sub.add_parser("report", description=REPORT_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    rp.add_argument("--project"); rp.add_argument("--since", required=True); rp.add_argument("--until"); rp.add_argument("--cwd")
    sub.add_parser("selftest")
    s = sub.add_parser("stats"); s.add_argument("--role"); s.add_argument("--kind"); s.add_argument("--project")
    s.add_argument("--json", action="store_true"); s.add_argument("--cwd")
    a = sub.add_parser("apply"); a.add_argument("--dry-run", action="store_true"); a.add_argument("--cwd")
    sd = sub.add_parser("seed"); sd.add_argument("--cwd")
    cf = sub.add_parser("config"); cf.add_argument("--get"); cf.add_argument("--cwd")
    stt = sub.add_parser("status"); stt.add_argument("--cwd"); stt.add_argument("--json", action="store_true")
    hd = sub.add_parser("held", description="Todo tickets the PM skipped for their blockers. `fleet status` names the ones "
                        "that can start now, stacked on the blockers' pushed branches.")
    hd.add_argument("action", choices=["set", "clear", "list"]); hd.add_argument("tickets", nargs="*")
    hd.add_argument("--blocked-by", help="set: the blocker tickets, comma separated"); hd.add_argument("--cwd")
    hd.add_argument("--json", action="store_true")
    fm = sub.add_parser("free-models"); fm.add_argument("action", nargs="?", default="list", choices=["list", "refresh"])
    fm.add_argument("--json", action="store_true"); fm.add_argument("--cwd")
    args, rest = ap.parse_known_args(argv)
    # Bare key=value words (log add ... duration_ms=1 tokens=2) land here wherever they sit on the
    # line; argparse would otherwise drop them or refuse them after an option.
    args.extra = [x for x in rest if "=" in x and not x.startswith("-")]
    bad = [x for x in rest if x not in args.extra]
    if bad or (args.extra and args.cmd != "log"):
        ap.error(f"unrecognized arguments: {' '.join(bad or args.extra)}")
    if args.cmd == "selftest":
        return selftest()
    reg = load_registry(getattr(args, "cwd", None) or os.getcwd(), getattr(args, "project", None))

    if args.cmd == "pick":
        rng = random.Random(args.seed) if args.seed is not None else random
        trig = [t.strip() for t in args.triggers.split(",") if t.strip()]
        print(json.dumps(pick(reg, args.role, args.kind, trig, args.urgent, args.attempt, args.pair_with, args.pair_experiment, rng), indent=2))
    elif args.cmd == "budget":
        if args.action in ("line", "status"):
            checks = [budget_check(reg, e) for e in reg.get("budget", {}).get("executors", {})]
            print(json.dumps(checks, indent=2) if args.json or args.action == "status" else budget_line(reg, checks))
        elif args.action == "check":
            c = budget_check(reg, args.executor, model=args.model)
            print(json.dumps(c) if args.json else f"{c['executor']}: {c['state']}" + (f" until {hhmm(c['resume_at'])}" if c["resume_at"] and c["state"] != "ok" else "") + (f" ({c['note']})" if c["note"] else ""))
            return 0 if c["state"] == "ok" else 3
        elif args.action == "backoff":
            until = budget_backoff(reg, args.executor, args.minutes, args.reason)
            print(f"{args.executor}: backoff until {hhmm(until)}")
        elif args.action == "lane-start":
            budget_record_lane_start(reg, args.executor)
        else:
            ap.error(f"unknown budget action {args.action}")
    elif args.cmd == "log":
        fields = parse_kv(args.extra)
        fields.update(parse_kv(args.set))
        if args.action == "add":
            ident, lane_res = {}, {}
            if args.from_result:
                ident, rfields, lane_res = lane_result_fields(args.from_result)
                for k, v in rfields.items():
                    fields.setdefault(k, v)  # numbers typed on the line win over the file
            for f in ("ticket", "role", "executor", "model", "effort"):
                if not getattr(args, f) and ident.get(f):
                    setattr(args, f, ident[f])
            for f in ("ticket", "role", "executor", "model", "outcome"):
                if not getattr(args, f) and f not in fields:
                    ap.error(f"log add needs --{f}")
            row = {"type": "spawn", "ts": now_iso(), "project": args.project or reg.get("_project"),
                   "ticket": args.ticket, "role": args.role, "task_kind": args.kind or "unknown",
                   "executor": args.executor, "model": args.model, "experiment": bool(args.experiment),
                   **({"effort": args.effort} if args.effort else {}),
                   "reason": args.reason, "outcome": args.outcome}
            if args.cause:
                fields["fail_cause"] = args.cause
            if args.defect:
                fields["defect"] = args.defect
            if args.in_list:
                fields["in_list"] = args.in_list == "yes"
            if args.severity:
                fields["severity"] = args.severity
            if args.repeat:
                fields["repeat"] = args.repeat == "yes"
            row.update(fields)
            if row["outcome"] not in OUTCOMES:
                ap.error(f"outcome must be one of {', '.join(OUTCOMES)}")
            if row["outcome"] in REASON_OUTCOMES and not (row.get("reason") or "").strip():
                said = lane_reason(lane_res)
                if not said:
                    ap.error(f"{row['outcome']} needs --reason: what stopped the session, in a few words")
                row["reason"] = said
            if row["outcome"] == "verify_fail" and row.get("fail_cause") not in FAIL_CAUSES:
                ap.error(f"verify_fail needs --cause {'|'.join(FAIL_CAUSES)}: only 'missed' counts against the model")
            if row["outcome"] == "verify_fail" and row.get("fail_cause") == "missed" and not row.get("defect") and not quiet:
                print(f"fleetctl: logged; add --defect {'|'.join(DEFECTS)} next time, so the review can count rework by class",
                      file=sys.stderr)
            dup = None if args.force else duplicate_of(reg, row)
            if dup is not None:
                print(f"fleetctl: not logged, it repeats a row already in the log: {dup.get('ts')} {dup.get('ticket')} "
                      f"{dup.get('role')} {dup.get('executor')}:{dup.get('model')} {dup.get('outcome')}"
                      + (f" agent {dup['agent_id']}" if dup.get("agent_id") else "")
                      + (f" cause {dup['fail_cause']}" if dup.get("fail_cause") else "")
                      + ". Fix that row with `log backfill`, or pass --force for a real second session.", file=sys.stderr)
                return 5
            append_row(reg, row)
            if not quiet:
                extra = " ".join(f"{k}={v}" for k, v in fields.items() if k != "result_path")
                print(f"logged {row['project']} {row['ticket']} {row['role']} {row['executor']}:{row['model']} {row['outcome']}"
                      + (f" {extra}" if extra else ""))
        else:
            sets = fields
            if not (args.ticket and args.role and sets):
                ap.error("log backfill needs --ticket, --role and --set k=v")
            append_row(reg, {"type": "backfill", "ts": now_iso(), "project": args.project or reg.get("_project"),
                             "ticket": args.ticket, "role": args.role, "fields": sets})
            print(f"backfilled {args.ticket} {args.role}: {', '.join(sets)}")
    elif args.cmd == "rounds":
        return run_rounds(args, reg, ap)
    elif args.cmd == "queue":
        return run_queue(args, reg, ap)
    elif args.cmd == "questions":
        return run_questions(args, reg, ap)
    elif args.cmd == "report":
        print(report(reg, args.project or reg.get("_project"), args.since, args.until))
    elif args.cmd == "cost":
        import fleetcost
        return fleetcost.run(sys.modules[__name__], args)
    elif args.cmd == "retro":
        import fleetretro
        return fleetretro.run(sys.modules[__name__], args)
    elif args.cmd == "review":
        import fleetreview
        return fleetreview.run(sys.modules[__name__], args)
    elif args.cmd == "stats":
        board = scoreboard(reg, load_rows(reg), args.role, args.kind, args.project)
        if args.json:
            print(json.dumps([{"role": k[0], "task_kind": k[1], "executor_model": k[2], **{x: y for x, y in v.items() if x != "recent_fp"}}
                              for k, v in sorted(board.items(), key=lambda kv: str(kv[0]))], indent=2))
        else:
            print_board(reg, board)
            if args.project is None:
                print(f"\nbudget: {budget_line(reg)}")
    elif args.cmd == "apply":
        rep = apply_changes(reg, args.dry_run)
        print("\n".join(rep) if rep else "no promotions or demotions")
    elif args.cmd == "config":
        cfg = project_config(args.cwd or os.getcwd())
        if args.get:
            for k in args.get.split("."):
                cfg = cfg.get(k) if isinstance(cfg, dict) else None
        print(json.dumps(cfg, indent=2))
    elif args.cmd == "status":
        import fleetstatus
        return fleetstatus.run(sys.modules[__name__], args)
    elif args.cmd == "held":
        import fleetstatus
        return fleetstatus.held_cmd(sys.modules[__name__], args)
    elif args.cmd == "free-models":
        pol = freemodels.policy(reg)
        if args.action == "refresh":
            exe = (reg.get("executors") or {}).get(pol["executor"]) or {}
            before = {k for k, v in (freemodels.load_state(STATE_HOME).get("models") or {}).items() if v.get("live")}
            found = {}
            for prov in pol.get("providers") or []:
                got, err = freemodels.discover(exe.get("binary") or pol["executor"], prov)
                if err:
                    print(f"free-models: {err}; the last list is kept", file=sys.stderr)
                    return 4
                for f in got:
                    found[f["model"]] = f
            st, eligible = freemodels.refresh(STATE_HOME, list(found.values()), pol,
                                              source=f"{exe.get('binary') or pol['executor']} models --refresh --verbose")
            live = {k for k, v in st["models"].items() if v.get("live")}
            new, gone = sorted(live - before), sorted(before - live)
            print(f"free models: {len(eligible)} usable of {len(live)} live"
                  + (f" · new: {', '.join(new)}" if new else "") + (f" · gone: {', '.join(gone)}" if gone else ""))
        st = freemodels.load_state(STATE_HOME)
        if args.json:
            print(json.dumps(st, indent=2))
        elif args.action == "list":
            print(freemodels.render(st, pol))
    elif args.cmd == "seed":
        n, by = seed(reg)
        print(f"seeded {n} rows " + json.dumps(by))
    return 0


if __name__ == "__main__":
    sys.exit(main())
