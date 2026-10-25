#!/usr/bin/env python3
"""freemodels — the free models opencode serves today, and who may use them.

New free models appear almost daily, some only for a short trial before a release, and others
go away. So the list is discovered, not written down: `run-lane.sh free-models refresh` asks
opencode, keeps the models that cost nothing, call tools and have enough context, and records
when each was first and last seen. `pick` adds the live ones as challengers for the roles the
owner allows (`free_model_policy.roles`) and removes free models from every other role. A free
tier may keep prompts, so by default only read-only scans get them.

Standard library only. Python 3.9.
"""
import datetime, json, os, re, subprocess

FREE_NAME = re.compile(r"^opencode/.+-free$")
DEFAULT_POLICY = {"roles": ["scan"], "executor": "opencode", "providers": ["opencode"],
                  "max_age_days": 3, "min_context": 128000, "require_toolcall": True}


def policy(reg):
    p = dict(DEFAULT_POLICY)
    p.update({k: v for k, v in (reg.get("free_model_policy") or {}).items() if not k.startswith("$")})
    return p


def state_path(state_home):
    return os.path.join(state_home, "free-models.json")


def load_state(state_home):
    try:
        with open(state_path(state_home)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def parse_verbose(text, provider):
    """`opencode models <provider> --verbose` prints '<provider>/<id>' then a JSON object, per model."""
    parts = re.split(r"(?m)^(" + re.escape(provider) + r"/\S+)\n(?=\{)", text)
    out = []
    for name, body in zip(parts[1::2], parts[2::2]):
        try:
            d = json.loads(body)
        except ValueError:
            continue
        cost = d.get("cost") or {}
        caps = d.get("capabilities") or {}
        out.append({"model": name, "free": not cost.get("input") and not cost.get("output"),
                    "toolcall": bool(caps.get("toolcall")), "context": (d.get("limit") or {}).get("context"),
                    "status": d.get("status"), "release_date": d.get("release_date"), "family": d.get("family"),
                    "variants": list((d.get("variants") or {}).keys())})
    return out


def discover(binary, provider, timeout=180):
    """(models, error). --refresh pulls the current list from models.dev first."""
    try:
        r = subprocess.run([binary, "models", provider, "--refresh", "--verbose"], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"{binary} failed: {e}"
    if r.returncode:
        return None, f"{binary} models failed: " + (r.stderr.strip().splitlines() or ["?"])[-1]
    models = parse_verbose(r.stdout, provider)
    if not models:
        return None, f"{binary} listed no {provider} models"
    return models, None


def refresh(state_home, found, pol, today=None, source=None):
    """Merge one discovery into the state. A model missing from it is kept, marked not live."""
    today = today or datetime.date.today().isoformat()
    st = load_state(state_home)
    models = st.get("models") or {}
    for m in models.values():
        m["live"] = False
    eligible = []
    for f in found:
        ok = f["free"] and f.get("status") != "deprecated" \
            and (f["toolcall"] or not pol.get("require_toolcall")) \
            and (f.get("context") or 0) >= int(pol.get("min_context") or 0)
        if not f["free"]:
            continue
        m = models.setdefault(f["model"], {"first_seen": today})
        m.update(last_seen=today, live=True, eligible=ok, toolcall=f["toolcall"], context=f.get("context"),
                 release_date=f.get("release_date"), family=f.get("family"), variants=f.get("variants"))
        if ok:
            eligible.append(f["model"])
    st.update(refreshed_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              source=source, models=dict(sorted(models.items())))
    os.makedirs(state_home, exist_ok=True)
    tmp = state_path(state_home) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2)
        f.write("\n")
    os.replace(tmp, state_path(state_home))
    return st, eligible


def fresh(st, pol, now=None):
    t = st.get("refreshed_at")
    if not t:
        return False
    try:
        d = datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - d).total_seconds() <= float(pol.get("max_age_days", 3)) * 86400


def known_free(reg, st):
    """Every model known to be free: discovered at any time, the registry's static list, or
    named '<opencode>/...-free'."""
    pol = policy(reg)
    static = ((reg.get("executors") or {}).get(pol["executor"]) or {}).get("free_models") or []
    return set((st.get("models") or {}).keys()) | set(static), pol


def is_free(reg, st, executor, model):
    known, pol = known_free(reg, st)
    return executor == pol["executor"] and (model in known or bool(FREE_NAME.match(str(model))))


def apply_policy(reg, role, cands, st, now=None):
    """(candidates, notes) for a role. Allowed roles keep their listed free models while those are
    live, and get every other live, eligible one appended as a challenger. Other roles lose all
    free models, whatever the registry or an override lists."""
    pol = policy(reg)
    notes = []
    allowed = role in (pol.get("roles") or [])
    is_fresh = fresh(st, pol, now)
    models = st.get("models") or {}
    out = []
    for c in cands:
        if not is_free(reg, st, c.get("executor"), c.get("model")):
            out.append(c)
        elif not allowed:
            notes.append(f"{c['model']} dropped: free models are for {', '.join(pol['roles']) or 'no role'} only")
        elif is_fresh and not (models.get(c["model"]) or {}).get("live"):
            seen = (models.get(c["model"]) or {}).get("last_seen")
            notes.append(f"{c['model']} dropped: not served now" + (f" (last seen {seen})" if seen else ""))
        else:
            out.append(c)
    if allowed and is_fresh:
        have = {(c.get("executor"), c.get("model")) for c in out}
        for name, m in models.items():
            if m.get("live") and m.get("eligible") and (pol["executor"], name) not in have:
                out.append({"executor": pol["executor"], "model": name, "free": True,
                            "first_seen": m.get("first_seen"), "note": f"free, discovered {m.get('first_seen')}"})
    elif allowed and models:
        notes.append(f"free model list is stale (refreshed {st.get('refreshed_at')}): run free-models refresh")
    return out, notes


def render(st, pol):
    L = [f"free models · refreshed {st.get('refreshed_at') or 'never'}"
         + ("" if st.get("refreshed_at") else " · run: run-lane.sh free-models refresh"),
         f"  allowed roles: {', '.join(pol['roles']) or 'none'} · need tool calls: {pol['require_toolcall']}"
         f" · min context {int(pol['min_context']) // 1000}k"]
    for name, m in sorted((st.get("models") or {}).items(), key=lambda kv: (not kv[1].get("live"), kv[0])):
        state = ("live" if m.get("eligible") else "live, not eligible") if m.get("live") else f"gone since {m.get('last_seen')}"
        L.append(f"  {name:<42}{state:<26}first seen {m.get('first_seen')}  released {m.get('release_date') or '?'}"
                 f"  {(m.get('context') or 0) // 1000}k")
    return "\n".join(L)


# ---------------------------------------------------------------- selftest
SAMPLE = """opencode/new-free
{"id": "new-free", "cost": {"input": 0, "output": 0}, "capabilities": {"toolcall": true}, "limit": {"context": 200000}, "status": "active", "release_date": "2026-10-24", "family": "new", "variants": {"low": {}, "high": {}}}
opencode/paid-pro
{"id": "paid-pro", "cost": {"input": 1.5, "output": 6}, "capabilities": {"toolcall": true}, "limit": {"context": 200000}}
opencode/tiny-free
{"id": "tiny-free", "cost": {"input": 0, "output": 0}, "capabilities": {"toolcall": true}, "limit": {"context": 32000}}
opencode/chat-free
{"id": "chat-free", "cost": {"input": 0, "output": 0}, "capabilities": {"toolcall": false}, "limit": {"context": 200000}}
"""


def selftest(check):
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix="freemodels-selftest-")
    try:
        reg = {"free_model_policy": {"roles": ["scan"]}, "executors": {"opencode": {"free_models": ["opencode/old-free"]}}}
        pol = policy(reg)
        found = parse_verbose(SAMPLE, "opencode")
        check("parse: four models", [f["model"] for f in found], ["opencode/new-free", "opencode/paid-pro", "opencode/tiny-free", "opencode/chat-free"])
        st, elig = refresh(d, found, pol, today="2026-10-24")
        check("only free, tool-calling, big enough", elig, ["opencode/new-free"])
        check("paid model not recorded", "opencode/paid-pro" in st["models"], False)
        scan = [{"executor": "claude", "model": "haiku"}, {"executor": "opencode", "model": "opencode/old-free"}]
        got, notes = apply_policy(reg, "scan", scan, st)
        check("scan gets the new free model, not the unseen listed one", [c["model"] for c in got], ["haiku", "opencode/new-free"])
        eng = [{"executor": "claude", "model": "sonnet"}, {"executor": "opencode", "model": "opencode/new-free"},
               {"executor": "opencode", "model": "opencode/unlisted-free"}]
        got, notes = apply_policy(reg, "engineer", eng, st)
        check("engineer never gets a free model", [c["model"] for c in got], ["sonnet"])
        st, elig = refresh(d, [f for f in found if f["model"] != "opencode/new-free"], pol, today="2026-10-25")
        check("a model that went away is kept as not live", (st["models"]["opencode/new-free"]["live"],
              st["models"]["opencode/new-free"]["first_seen"], st["models"]["opencode/new-free"]["last_seen"]),
              (False, "2026-10-24", "2026-10-24"))
        got, notes = apply_policy(reg, "scan", [{"executor": "opencode", "model": "opencode/new-free"}], st)
        check("a gone model is dropped from scan", (got, any("not served now" in n for n in notes)), ([], True))
        old = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10)
        got, notes = apply_policy(reg, "scan", [], st, now=old)
        check("a stale list adds nothing and says so", (got, any("stale" in n for n in notes)), ([], True))
    finally:
        shutil.rmtree(d, ignore_errors=True)
