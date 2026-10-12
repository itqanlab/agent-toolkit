#!/usr/bin/env python3
"""fleetctl — executor selection, budget, outcomes log and scoreboard for the Plane fleet.

One module, used by the PM (through run-lane.sh), by run-lane.mjs before it launches a lane,
and by the Claude usage-pacer hook. Standard library only. Never prints secrets.

  fleetctl.py pick    --role R [--kind K] [--triggers a,b] [--urgent] [--attempt N]
                      [--pair-with exe:model [--pair-experiment]] [--cwd DIR] [--seed N]
  fleetctl.py budget  [status|line|check EXE|backoff EXE [--minutes M] [--reason TEXT]|lane-start EXE] [--json]
  fleetctl.py log     add --ticket T --role R --executor E --model M --outcome O [--kind K] [k=v ...]
  fleetctl.py log     backfill --ticket T --role R --set k=v [k=v ...]
  fleetctl.py stats   [--role R] [--kind K] [--project P] [--json]
  fleetctl.py apply   [--dry-run]          promotions / demotions -> user override + decisions log
  fleetctl.py seed                          fold legacy run-log rows (log.legacy_glob) into the log
  fleetctl.py config  [--get a.b.c] [--cwd DIR]   .plane/config.json + the per-user project override

Layers, later wins: <this dir>/../executors.json  <  user override (log.user_override)
  <  user override projects.<project>  <  <repo>/.plane/config.json fleet.executors
"""
import argparse, datetime, glob, hashlib, json, os, random, re, subprocess, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))       # <fleet root>/scripts/lanes/
BASE_REGISTRY = os.path.join(FLEET_ROOT, "references", "executors.json")
STATE_HOME = os.environ.get("PLANE_FLEET_HOME") or os.path.expanduser("~/.config/plane-fleet")
OUTCOMES = ("pr_opened", "blocked", "verify_pass", "verify_fail", "done", "lane_failed", "stale", "deferred")
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


def budget_check(reg, exe, now=None):
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
    if used >= hard:
        res.update(state="stop", resume_at=resets)
        return res
    if window and resets and not switch_on(reg, exe, "pace-off"):
        elapsed = max(0.0, min(1.0, (now - (resets - window)) / window))
        allowed = min(hard, elapsed * 100 + allow)
        if used > allowed:
            catch_up = (resets - window) + (used - allow) / 100 * window
            res.update(state="hold", resume_at=min(catch_up, resets), note=f"ahead of pace ({allowed:.0f}% allowed now)")
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


LABELS = {"claude": "Claude", "codex": "Codex", "opencode": "Ollama"}


def budget_line(reg, checks=None):
    checks = checks or [budget_check(reg, e) for e in reg.get("budget", {}).get("executors", {})]
    parts = []
    for c in checks:
        lab = LABELS.get(c["executor"], c["executor"])
        if c["used_pct"] is not None:
            w = c.get("window_minutes") or 0
            span = "wk" if w >= 7 * 24 * 60 else (f"{w // 60}h" if w else "")
            s = f"{lab} {c['used_pct']:.0f}%" + (f" ({span})" if span else "")
        elif c.get("note") == "pacer off":
            s = f"{lab} pacer off"
        elif c["executor"] == "opencode":
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
    live = {r["source_key"]: r for r in legacy_rows(reg)}
    merged = []
    for r in spawns:
        k = r.get("source_key")
        merged.append(live.pop(k) if k and k in live else r)
    merged += live.values()
    merged.sort(key=lambda r: r.get("ts") or "")
    for b in sorted(backfills, key=lambda r: r.get("ts") or ""):
        for r in reversed(merged):
            if (r.get("ticket"), r.get("role")) == (b.get("ticket"), b.get("role")) and \
               (not b.get("project") or r.get("project") == b.get("project")) and (r.get("ts") or "") <= (b.get("ts") or "~"):
                r.update(b.get("fields", {}))
                break
    derive_quality(merged)
    return merged


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
        if role == "engineer" and q is None and r.get("outcome") in ("pr_opened", "done", "verify_pass", "verify_fail"):
            for t in by_ticket.get((r.get("project"), r.get("ticket")), []):
                if t.get("role") in ("tester", "verifier-legacy") and (t.get("ts") or "") > (r.get("ts") or "") \
                        and t.get("outcome") in ("verify_pass", "verify_fail"):
                    q = t.get("outcome") == "verify_pass"
                    break
        elif role == "tester":
            q = None
            if "reverted" in r or "bug_filed" in r:
                q = not r.get("reverted") and not r.get("bug_filed")
        r["quality"] = q


def append_row(reg, row):
    path = P(reg, "path")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def parse_kv(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"fleetctl: expected key=value, got {it!r}")
        k, v = it.split("=", 1)
        try:
            out[k] = json.loads(v)
        except Exception:
            out[k] = v
    return out


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- stats
def cost_units(reg, r):
    w = reg.get("cost_weights", {})
    key = f"{r.get('executor')}:{r.get('model')}"
    weight = w.get(key, w.get(r.get("executor") or "", None))
    tok = r.get("tokens")
    if isinstance(tok, dict):  # codex usage block
        tok = (tok.get("input_tokens", 0) - tok.get("cached_input_tokens", 0)) + tok.get("output_tokens", 0)
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
        if r.get("type", "spawn") != "spawn" or r.get("outcome") in ("deferred",):
            continue
        if role and r.get("role") != role:
            continue
        if project and r.get("project") != project:
            continue
        exe = f"{r.get('executor') or 'claude'}:{r.get('model')}"
        for k in (r.get("task_kind") or "unknown", "*"):
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
    return f"{c['executor']}:{c['model']}"


def family(reg, c):
    fam = reg.get("families", {})
    if c["executor"] == "opencode":
        for k, v in fam.items():
            if k.startswith("opencode:") and str(c["model"]).startswith(k.split(":", 1)[1]):
                return v
    return fam.get(c["executor"], c["executor"])


def candidates_for(reg, role, kind):
    table = (reg.get("candidates") or {}).get(role) or {}
    lst = table.get(kind) if kind and kind in table else table.get("*")
    return [c for c in (lst or []) if isinstance(c, dict)], (kind if kind in table else "*")


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
        cands, list_kind = candidates_for(reg, role, kind)
        pinned = not portable
        out["reason"] = f"champion for {role}/{list_kind}"
    if not cands:
        fb = (reg.get("fallback") or {}).get(role) or {"executor": "claude", "model": None}
        cands, out["reason"] = [fb], "no candidates: fallback"
    execs = sorted({c["executor"] for c in cands} | {((reg.get("fallback") or {}).get(role) or {}).get("executor", "claude")})
    order = list(reg.get("budget", {}).get("executors", {})) + [e for e in execs if e not in reg.get("budget", {}).get("executors", {})]
    checks = {e: budget_check(reg, e) for e in order}
    out["budget"] = budget_line(reg, list(checks.values()))
    ok = lambda c: checks.get(c["executor"], {"state": "ok"})["state"] == "ok"

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
        count = lambda c: sum(1 for r in rows if r.get("role") == role and f"{r.get('executor')}:{r.get('model')}" == ckey(c)
                              and (list_kind == "*" or r.get("task_kind") == list_kind))
        chosen = min(challengers, key=count)
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
                out["reason"] = f"budget: {champ['executor']} {checks[champ['executor']]['state']} → {ckey(nxt)}"
        if chosen is None:
            resumes = [checks[c["executor"]]["resume_at"] for c in cands if checks.get(c["executor"], {}).get("resume_at")]
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
    out.update(decision="spawn", executor=chosen["executor"], model=chosen["model"],
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
    for role, table in (reg.get("candidates") or {}).items():
        if not isinstance(table, dict):
            continue
        for kind, lst in table.items():
            if kind.startswith("$") or not isinstance(lst, list) or len(lst) < 2:
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
                k = json.loads(line).get("source_key")
                if k:
                    have.add(k)
            except Exception:
                pass
    except OSError:
        pass
    added = 0
    by_project = {}
    for r in legacy_rows(reg):
        if r["source_key"] in have:
            continue
        append_row(reg, r)
        have.add(r["source_key"])
        added += 1
        by_project[r["project"]] = by_project.get(r["project"], 0) + 1
    return added, by_project


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
def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleetctl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick"); p.add_argument("--role", required=True); p.add_argument("--kind")
    p.add_argument("--triggers", default=""); p.add_argument("--urgent", action="store_true")
    p.add_argument("--attempt", type=int, default=0); p.add_argument("--pair-with")
    p.add_argument("--pair-experiment", action="store_true"); p.add_argument("--cwd"); p.add_argument("--seed", type=int)
    b = sub.add_parser("budget"); b.add_argument("action", nargs="?", default="line")
    b.add_argument("executor", nargs="?"); b.add_argument("--minutes", type=float); b.add_argument("--reason", default="rate limited")
    b.add_argument("--json", action="store_true"); b.add_argument("--cwd")
    lg = sub.add_parser("log"); lg.add_argument("action", choices=["add", "backfill"])
    for f in ("ticket", "role", "executor", "model", "outcome", "kind", "project", "cwd", "reason"):
        lg.add_argument(f"--{f}")
    lg.add_argument("--experiment", action="store_true"); lg.add_argument("--set", nargs="*", default=[]); lg.add_argument("extra", nargs="*")
    s = sub.add_parser("stats"); s.add_argument("--role"); s.add_argument("--kind"); s.add_argument("--project")
    s.add_argument("--json", action="store_true"); s.add_argument("--cwd")
    a = sub.add_parser("apply"); a.add_argument("--dry-run", action="store_true"); a.add_argument("--cwd")
    sd = sub.add_parser("seed"); sd.add_argument("--cwd")
    cf = sub.add_parser("config"); cf.add_argument("--get"); cf.add_argument("--cwd")
    args = ap.parse_args(argv)
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
            c = budget_check(reg, args.executor)
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
        if args.action == "add":
            for f in ("ticket", "role", "executor", "model", "outcome"):
                if not getattr(args, f) and f not in fields:
                    ap.error(f"log add needs --{f}")
            row = {"type": "spawn", "ts": now_iso(), "project": args.project or reg.get("_project"),
                   "ticket": args.ticket, "role": args.role, "task_kind": args.kind or "unknown",
                   "executor": args.executor, "model": args.model, "experiment": bool(args.experiment),
                   "reason": args.reason, "outcome": args.outcome}
            row.update(fields)
            if row["outcome"] not in OUTCOMES:
                ap.error(f"outcome must be one of {', '.join(OUTCOMES)}")
            append_row(reg, row)
            print(f"logged {row['project']} {row['ticket']} {row['role']} {row['executor']}:{row['model']} {row['outcome']}")
        else:
            sets = parse_kv(args.set)
            if not (args.ticket and args.role and sets):
                ap.error("log backfill needs --ticket, --role and --set k=v")
            append_row(reg, {"type": "backfill", "ts": now_iso(), "project": args.project or reg.get("_project"),
                             "ticket": args.ticket, "role": args.role, "fields": sets})
            print(f"backfilled {args.ticket} {args.role}: {', '.join(sets)}")
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
    elif args.cmd == "seed":
        n, by = seed(reg)
        print(f"seeded {n} rows " + json.dumps(by))
    return 0


if __name__ == "__main__":
    sys.exit(main())
