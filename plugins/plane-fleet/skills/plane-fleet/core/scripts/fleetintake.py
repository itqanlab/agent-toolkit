#!/usr/bin/env python3
"""Intake sources: feeds of work (an error tracker, any command) turned into ticket candidates.

  fleet intake [--cwd DIR]                     every source's new items, as JSON on stdout
  fleet intake check [--cwd DIR]               which sources are on, and whether each one answers
  fleet intake mark <source> <id> --ticket T   remember an item was filed, so it is not offered again
  fleet intake resolve <source> <id> --release SHA [--ticket T]
                                               tell the source the fix shipped (Sentry: resolved in that release)

Two kinds of source, both read from the project config (`fleet config`):
  - Sentry, built in. On whenever the config has a `sentry` block, and only for the Sentry
    projects that block names. A repo that ships a Sentry SDK but has no block gets a warning.
  - Commands, `fleet.intake_sources[]`, each printing {"items": [...]} (core/references/intake-sources.md).

Read-only except `mark` (local state) and `resolve`. A broken source never fails `fleet intake`:
it shows up as ok=false with an error, and its items are empty. Plane is never called from here;
the PM dedupes against the board with the plane MCP and files through the planner.
"""
import argparse
import json
import os
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SEVERITIES = ("urgent", "high", "medium", "low")
SENTRY_DEFAULTS = {
    "environment": "production", "token_env": "SENTRY_AUTH_TOKEN", "window_days": 7,
    "min_users": 2, "min_events": 5, "urgent_users": 5, "always": [], "urgent_paths": [],
    "ignore": [], "max_per_run": 5,
}
SDK_MARKERS = (("package.json", re.compile(r'"@sentry/[a-z-]+"')),
               ("requirements.txt", re.compile(r"^sentry-sdk", re.M)),
               ("pyproject.toml", re.compile(r"sentry-sdk")),
               ("Gemfile", re.compile(r"sentry-ruby")),
               ("go.mod", re.compile(r"getsentry/sentry-go")))
EVIDENCE_MAX = 1500


class SourceError(Exception):
    pass


# ---------------------------------------------------------------- config and state
def fleetctl():
    sys.path.insert(0, HERE)
    import fleetctl as fc
    return fc


def load(cwd):
    fc = fleetctl()
    cwd = os.path.abspath(cwd or os.getcwd())
    top = fc.git(cwd, "rev-parse", "--show-toplevel") or cwd
    return fc.project_config(cwd) or {}, top, fc.project_of(cwd), fc.STATE_HOME


def state_path(home, project):
    return os.path.join(home, "state", f"intake-{project or 'default'}.json")


def read_state(home, project):
    try:
        with open(state_path(home, project)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_state(home, project, st):
    p = state_path(home, project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2, sort_keys=True)
    os.replace(tmp, p)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- scrubbing
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<![\w-])\+?\d[\d\s-]{6,}\d(?![\w-])")
SECRETISH = re.compile(r"(?i)\b(bearer|token|key|secret|password|pass|auth)([=: ]+)\S+")


def strip_query(url):
    return re.split(r"[?#]", url or "", 1)[0]


def scrub(text):
    text = SECRETISH.sub(lambda m: m.group(1) + m.group(2) + "[redacted]", text or "")
    text = EMAIL.sub("[email]", text)
    return PHONE.sub("[number]", text)


# ---------------------------------------------------------------- sentry
def sentry_token(sc):
    tok = os.environ.get(sc.get("token_env") or SENTRY_DEFAULTS["token_env"], "").strip()
    if tok:
        return tok, None
    path = os.path.expanduser(sc.get("token_file") or "")
    if not sc.get("token_file"):
        return None, f"no token: set ${sc.get('token_env') or SENTRY_DEFAULTS['token_env']} or sentry.token_file"
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        with open(path) as f:
            tok = f.read().strip()
    except OSError:
        return None, f"no token: sentry.token_file {path} is not readable"
    warn = f"sentry.token_file {path} is readable by others; chmod 600 it" if mode & 0o077 else None
    return (tok or None), (warn if tok else f"no token: sentry.token_file {path} is empty")


def http_json(method, url, token, body=None, timeout=25):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "plane-fleet-intake"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "null"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise SourceError(f"Sentry refused the token (HTTP {e.code})")
        raise SourceError(f"Sentry answered HTTP {e.code} for {strip_query(url)}")
    except (urllib.error.URLError, OSError) as e:
        raise SourceError(f"Sentry not reachable: {getattr(e, 'reason', e)}")
    try:
        return json.loads(raw)
    except ValueError:
        raise SourceError("Sentry sent a reply that is not JSON")


class Sentry:
    def __init__(self, sc, fetch=None):
        self.sc = {**SENTRY_DEFAULTS, **sc}
        self.base = f"https://{self.sc.get('host') or 'sentry.io'}/api/0"
        self.org = self.sc.get("org")
        self.fetch = fetch
        self.token = None

    def call(self, method, path, body=None):
        if self.fetch:
            return self.fetch(method, path, body)
        if not self.token:
            tok, err = sentry_token(self.sc)
            if not tok:
                raise SourceError(err)
            self.token = tok
        return http_json(method, self.base + path, self.token, body)

    def problems(self):
        out = []
        if not self.org:
            out.append("sentry.org is missing")
        if not self.sc.get("projects"):
            out.append("sentry.projects is empty: name this repo's Sentry projects, never the whole org")
        return out

    def project_ids(self):
        ids = {}
        for slug in self.sc["projects"]:
            p = self.call("GET", f"/projects/{self.org}/{urllib.parse.quote(slug)}/")
            if not isinstance(p, dict) or not p.get("id"):
                raise SourceError(f"Sentry project {self.org}/{slug} not found")
            ids[str(p["id"])] = slug
        return ids

    def issues(self):
        ids = self.project_ids()
        q = urllib.parse.urlencode([("query", "is:unresolved"), ("environment", self.sc["environment"]),
                                    ("statsPeriod", "14d"), ("sort", "freq"), ("limit", "100")]
                                   + [("project", i) for i in ids])
        rows = self.call("GET", f"/organizations/{self.org}/issues/?{q}") or []
        # The org endpoint is scoped by project id; drop anything that still isn't ours.
        return [r for r in rows if str((r.get("project") or {}).get("id")) in ids
                or (r.get("project") or {}).get("slug") in self.sc["projects"]]

    def qualifies(self, r, now=None):
        sc = self.sc
        now = now or datetime.now(timezone.utc)
        title = r.get("title") or ""
        if any(s and s in title for s in sc["ignore"]) or str(r.get("id")) in map(str, sc["ignore"]) \
                or r.get("shortId") in sc["ignore"]:
            return False
        regressed = r.get("substatus") == "regressed"
        first = parse_ts(r.get("firstSeen"))
        recent = bool(first and first >= now - timedelta(days=float(sc["window_days"])))
        if not (recent or regressed):
            return False
        slug = (r.get("project") or {}).get("slug")
        users, count = int(r.get("userCount") or 0), int(r.get("count") or 0)
        return slug in sc["always"] or users >= int(sc["min_users"]) or count >= int(sc["min_events"])

    def severity(self, r):
        sc = self.sc
        users = int(r.get("userCount") or 0)
        where = " ".join(str(r.get(k) or "") for k in ("culprit", "title"))
        if users >= int(sc["urgent_users"]) or any(p and p in where for p in sc["urgent_paths"]):
            return "urgent"
        if (r.get("project") or {}).get("slug") in sc["always"] or users >= int(sc["min_users"]) \
                or r.get("substatus") == "regressed":
            return "high"
        return "medium"

    def evidence(self, r):
        lines = [f"{r.get('shortId')} in {(r.get('project') or {}).get('slug')}, {self.sc['environment']}",
                 f"title: {r.get('title')}", f"where: {r.get('culprit') or '-'}",
                 f"events {r.get('count')}, users {r.get('userCount')}, first {r.get('firstSeen')}, "
                 f"last {r.get('lastSeen')}, status {r.get('substatus') or '-'}",
                 f"link: {r.get('permalink') or ''}"]
        try:
            ev = self.call("GET", f"/organizations/{self.org}/issues/{r['id']}/events/latest/") or {}
        except SourceError as e:
            ev = {}
            lines.append(f"(latest event not read: {e})")
        tags = {t.get("key"): t.get("value") for t in ev.get("tags") or []}
        for key in ("release", "url", "transaction", "browser", "os"):
            if tags.get(key):
                lines.append(f"{key}: {strip_query(str(tags[key]))}")
        for entry in ev.get("entries") or []:
            if entry.get("type") == "exception":
                vals = (entry.get("data") or {}).get("values") or []
                if vals:
                    frames = ((vals[-1].get("stacktrace") or {}).get("frames") or [])
                    app = [f for f in frames if f.get("inApp")] or frames
                    lines.append("frames (innermost last):")
                    lines += [f"  {f.get('filename')}:{f.get('lineNo')} {f.get('function') or ''}".rstrip()
                              for f in app[-4:]]
            if entry.get("type") == "breadcrumbs":
                crumbs = ((entry.get("data") or {}).get("values") or [])[-4:]
                if crumbs:
                    lines.append("last breadcrumbs:")
                for b in crumbs:
                    d = b.get("data") or {}
                    bits = [b.get("category") or b.get("type") or "?"]
                    for k in ("method", "status_code", "url", "from", "to"):
                        if d.get(k) is not None:
                            bits.append(f"{k}={strip_query(str(d[k]))}")
                    lines.append("  " + " ".join(bits))
        # The link is Sentry's own permalink; it goes in after scrubbing so its issue number survives.
        link = f"link: {strip_query(r.get('permalink') or '')}\n"
        text = link + scrub("\n".join(lines))
        return text if len(text) <= EVIDENCE_MAX else text[:EVIDENCE_MAX - 1] + "…"

    def items(self, now=None):
        rows = [r for r in self.issues() if self.qualifies(r, now)]
        rows.sort(key=lambda r: (SEVERITIES.index(self.severity(r)), -int(r.get("userCount") or 0),
                                 -int(r.get("count") or 0)))
        out = []
        for r in rows:
            out.append({"external_id": str(r["id"]), "title": scrub(f"{r.get('shortId')}: {r.get('title')}")[:200],
                        "url": r.get("permalink") or "", "severity": self.severity(r),
                        "regressed": r.get("substatus") == "regressed", "_row": r})
        return out

    def resolve(self, external_id, release, note=None):
        body = {"status": "resolved", "statusDetails": {"inRelease": release} if release else {}}
        self.call("PUT", f"/organizations/{self.org}/issues/{urllib.parse.quote(str(external_id))}/", body)
        if note:
            self.call("POST", f"/organizations/{self.org}/issues/{urllib.parse.quote(str(external_id))}/comments/",
                      {"text": note})


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def sdk_without_config(cfg, top):
    if cfg.get("sentry"):
        return None
    for name, rx in SDK_MARKERS:
        try:
            with open(os.path.join(top, name)) as f:
                if rx.search(f.read()):
                    return (f"this repo ships a Sentry SDK ({name}) but .plane/config.json has no `sentry` "
                            "block, so Sentry issues never reach the board. Add one "
                            "(core/references/intake-sources.md).")
        except OSError:
            continue
    return None


# ---------------------------------------------------------------- command sources
def run_command_source(src, top, runner=None):
    cmd = src.get("command")
    if not cmd:
        raise SourceError("no command")
    runner = runner or (lambda c: subprocess.run(c, shell=True, cwd=top, capture_output=True, text=True, timeout=120))
    try:
        p = runner(cmd)
    except subprocess.TimeoutExpired:
        raise SourceError("command timed out after 120s")
    if p.returncode != 0:
        tail = (p.stderr or "").strip().splitlines()[-1:] or [""]
        raise SourceError(f"command exited {p.returncode}: {scrub(tail[0])[:200]}")
    try:
        data = json.loads(p.stdout or "")
    except ValueError:
        raise SourceError("command output is not JSON")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise SourceError('command output has no "items" list')
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("external_id") or not it.get("title"):
            continue
        sev = it.get("severity") if it.get("severity") in SEVERITIES else "medium"
        out.append({"external_id": str(it["external_id"]), "title": scrub(str(it["title"]))[:200],
                    "url": str(it.get("url") or ""), "severity": sev,
                    "regressed": bool(it.get("regression_of") or it.get("regressed")),
                    "evidence": scrub(str(it.get("evidence") or ""))[:EVIDENCE_MAX]})
    out.sort(key=lambda i: SEVERITIES.index(i["severity"]))
    return out


# ---------------------------------------------------------------- the pass
def sources_of(cfg):
    out = []
    if cfg.get("sentry"):
        sc = cfg["sentry"]
        out.append({"name": sc.get("name") or "sentry", "kind": "sentry", "external_source": "sentry",
                    "max_per_run": int(sc.get("max_per_run") or SENTRY_DEFAULTS["max_per_run"]), "conf": sc})
    for src in ((cfg.get("fleet") or {}).get("intake_sources") or []):
        if src.get("name") and src.get("command"):
            out.append({"name": src["name"], "kind": "command", "external_source": src.get("external_source") or src["name"],
                        "max_per_run": int(src.get("max_per_run") or 5), "conf": src})
    return out


def collect(cfg, top, state, sentry_fetch=None, runner=None, now=None):
    """One pass over every source. Items already filed (and not since resolved) are left out; an item
    filed, resolved and back again comes out with regression_of = the old ticket."""
    result = {"sources": [], "warnings": []}
    w = sdk_without_config(cfg, top)
    if w:
        result["warnings"].append(w)
    for src in sources_of(cfg):
        row = {"name": src["name"], "external_source": src["external_source"], "ok": True, "error": None,
               "items": [], "skipped_filed": 0, "over_cap": 0}
        seen = state.get(src["name"]) or {}
        try:
            if src["kind"] == "sentry":
                s = Sentry(src["conf"], fetch=sentry_fetch)
                bad = s.problems()
                if bad:
                    raise SourceError("; ".join(bad))
                if not sentry_fetch:
                    _, warn = sentry_token(s.sc)
                    if warn and not warn.startswith("no token"):
                        result["warnings"].append(warn)
                cands = s.items(now)
            else:
                cands = run_command_source(src["conf"], top, runner)
            kept = []
            for it in cands:
                prev = seen.get(it["external_id"])
                if prev and prev.get("status") != "resolved":
                    row["skipped_filed"] += 1
                    continue
                it["regression_of"] = prev.get("ticket") if prev else None
                kept.append(it)
            row["over_cap"] = max(0, len(kept) - src["max_per_run"])
            kept = kept[:src["max_per_run"]]
            if src["kind"] == "sentry":
                for it in kept:
                    it["evidence"] = s.evidence(it.pop("_row"))
            for it in kept:
                it.pop("_row", None)
                it.pop("regressed", None)
            row["items"] = kept
        except SourceError as e:
            row.update(ok=False, error=str(e), items=[])
        result["sources"].append(row)
    return result


# ---------------------------------------------------------------- cli
def cmd_check(cfg, top, sentry_fetch=None, runner=None, out=print):
    srcs = sources_of(cfg)
    w = sdk_without_config(cfg, top)
    bad = 0
    if w:
        out(f"warning: {w}")
    if not srcs:
        out("intake: no sources configured")
        return 1 if w else 0
    res = collect(cfg, top, {}, sentry_fetch=sentry_fetch, runner=runner)
    for row, src in zip(res["sources"], srcs):
        scope = ""
        if src["kind"] == "sentry":
            sc = src["conf"]
            scope = f" {sc.get('org')}/{','.join(sc.get('projects') or [])} env={sc.get('environment') or SENTRY_DEFAULTS['environment']}"
        if row["ok"]:
            out(f"ok   {row['name']}{scope}: {len(row['items']) + row['over_cap']} new item(s)")
        else:
            bad += 1
            out(f"FAIL {row['name']}{scope}: {row['error']}")
    for x in res["warnings"]:
        if x != w:
            out(f"warning: {x}")
    return 1 if bad else 0


def cmd_resolve(cfg, top, home, project, source, external_id, release, ticket, sentry_fetch=None, runner=None):
    src = next((s for s in sources_of(cfg) if s["name"] == source), None)
    if not src:
        print(f"intake: no source named {source}", file=sys.stderr)
        return 2
    try:
        if src["kind"] == "sentry":
            note = f"Fixed by {ticket}, shipped in {release}." if ticket else None
            Sentry(src["conf"], fetch=sentry_fetch).resolve(external_id, release, note)
        else:
            rc = src["conf"].get("resolve_command")
            if not rc:
                print(f"intake: {source} has no resolve_command; nothing to tell it", file=sys.stderr)
            else:
                runner = runner or (lambda c: subprocess.run(c, shell=True, cwd=top, capture_output=True, text=True, timeout=120))
                import shlex
                p = runner(f"{rc} {shlex.quote(str(external_id))} {shlex.quote(release or '')}")
                if p.returncode != 0:
                    raise SourceError(f"resolve_command exited {p.returncode}")
    except SourceError as e:
        print(f"intake: {source} {external_id} not resolved: {e}", file=sys.stderr)
        return 1
    st = read_state(home, project)
    rec = st.setdefault(source, {}).setdefault(str(external_id), {})
    rec.update(status="resolved", release=release, resolved_at=now_iso(), **({"ticket": ticket} if ticket else {}))
    write_state(home, project, st)
    print(f"resolved {source} {external_id}" + (f" in {release}" if release else ""))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleet intake", description=__doc__.split("\n\n")[0])
    ap.add_argument("action", nargs="?", default="run", choices=["run", "check", "mark", "resolve", "selftest"])
    ap.add_argument("source", nargs="?")
    ap.add_argument("external_id", nargs="?")
    ap.add_argument("--ticket")
    ap.add_argument("--release")
    ap.add_argument("--cwd")
    a = ap.parse_args(argv)
    if a.action == "selftest":
        ok = [True]
        def check(name, got, want):
            good = got == want
            ok[0] &= good
            print(f"{'ok  ' if good else 'FAIL'} {name}: {got!r}" + ("" if good else f" (want {want!r})"))
        selftest(check)
        return 0 if ok[0] else 1
    cfg, top, project, home = load(a.cwd)
    if a.action == "check":
        return cmd_check(cfg, top)
    if a.action in ("mark", "resolve") and not (a.source and a.external_id):
        ap.error(f"{a.action} needs <source> <external_id>")
    if a.action == "mark":
        if not a.ticket:
            ap.error("mark needs --ticket")
        st = read_state(home, project)
        st.setdefault(a.source, {})[str(a.external_id)] = {"ticket": a.ticket, "status": "filed", "filed_at": now_iso()}
        write_state(home, project, st)
        print(f"marked {a.source} {a.external_id} as {a.ticket}")
        return 0
    if a.action == "resolve":
        return cmd_resolve(cfg, top, home, project, a.source, a.external_id, a.release, a.ticket)
    print(json.dumps(collect(cfg, top, read_state(home, project)), indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- selftest (fixtures, no network)
def selftest(check):
    import tempfile
    from types import SimpleNamespace
    now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    recent, old = "2026-11-18T10:00:00Z", "2026-09-01T10:00:00Z"

    def issue(i, slug, title, users, count, first=recent, sub="new", culprit=""):
        return {"id": str(i), "shortId": f"S-{i}", "title": title, "culprit": culprit, "userCount": users,
                "count": count, "firstSeen": first, "lastSeen": recent, "substatus": sub,
                "permalink": f"https://sentry.example/issues/{i}/", "project": {"id": {"web": "11", "api": "22"}.get(slug, "33"), "slug": slug}}
    rows = [issue(1, "api", "PrismaError P2028", 1, 1),                       # server: any qualifies -> high
            issue(2, "web", "TypeError: x is null", 1, 2),                     # client below both thresholds -> out
            issue(3, "web", "Failed to fetch module", 6, 40, culprit="/home"), # 6 users -> urgent
            issue(4, "web", "Object captured as exception with keys: a", 9, 50),  # ignored by title
            issue(5, "web", "Old but regressed", 2, 3, first=old, sub="regressed"),  # regression -> high
            issue(6, "web", "Old, still going", 3, 30, first=old, sub="ongoing"),    # old, not regressed -> out
            issue(7, "web", "Payment page broke", 1, 5, culprit="/payments/checkout"),  # urgent path
            issue(8, "other", "Someone else's project", 9, 99)]                # not our project -> dropped
    latest = {"tags": [{"key": "release", "value": "abc123"},
                       {"key": "url", "value": "https://app.example/customers?phone=01012345678"}],
              "entries": [{"type": "exception", "data": {"values": [{"stacktrace": {"frames": [
                  {"filename": "node_modules/x.js", "lineNo": 1, "inApp": False},
                  {"filename": "src/pay.ts", "lineNo": 42, "function": "submit", "inApp": True}]}}]}},
                  {"type": "breadcrumbs", "data": {"values": [
                      {"category": "xhr", "data": {"method": "GET", "status_code": 500,
                                                   "url": "/api/v1/customers?email=a@b.co"}},
                      {"category": "console", "message": "user ahmed@example.com token=sk_live_123 called 01012345678"}]}}]}
    calls = []

    def fetch(method, path, body):
        calls.append((method, path, body))
        if path.startswith("/projects/acme/web/"):
            return {"id": "11"}
        if path.startswith("/projects/acme/api/"):
            return {"id": "22"}
        if "/events/latest/" in path:
            return latest
        if path.startswith("/organizations/acme/issues/?"):
            return rows
        return {}
    sc = {"org": "acme", "projects": ["web", "api"], "environment": "prod", "always": ["api"],
          "urgent_paths": ["/payments"], "ignore": ["Object captured as exception with keys"], "max_per_run": 10}
    cfg = {"sentry": sc}
    top = tempfile.mkdtemp(prefix="fleetintake-selftest-")
    res = collect(cfg, top, {}, sentry_fetch=fetch, now=now)
    src = res["sources"][0]
    got = [(i["external_id"], i["severity"]) for i in src["items"]]
    check("intake: qualifying rules and severity order", got,
          [("3", "urgent"), ("7", "urgent"), ("5", "high"), ("1", "high")])
    q = next(p for m, p, _ in calls if p.startswith("/organizations/acme/issues/?"))
    check("intake: issues query names only this repo's projects and env",
          ("project=11" in q, "project=22" in q, "environment=prod" in q), (True, True, True))
    ev = src["items"][0]["evidence"]
    check("intake: evidence keeps in-app frame and release", ("src/pay.ts:42 submit" in ev, "release: abc123" in ev), (True, True))
    check("intake: evidence has no query, email, phone, token or console text",
          [s in ev for s in ("phone=", "01012345678", "a@b.co", "ahmed@example.com", "sk_live_123", "?email")], [False] * 6)
    check("intake: evidence link keeps the issue number", "https://sentry.example/issues/3/" in ev, True)
    check("intake: no item from another project", any(i["external_id"] == "8" for i in src["items"]), False)

    capped = collect({"sentry": {**sc, "max_per_run": 2}}, top, {}, sentry_fetch=fetch, now=now)["sources"][0]
    check("intake: cap per run, highest first", ([i["external_id"] for i in capped["items"]], capped["over_cap"]), (["3", "7"], 2))

    st = {"sentry": {"3": {"ticket": "P-1", "status": "filed"}, "5": {"ticket": "P-2", "status": "resolved"}}}
    again = collect(cfg, top, st, sentry_fetch=fetch, now=now)["sources"][0]
    ids = {i["external_id"]: i["regression_of"] for i in again["items"]}
    check("intake: a filed item is not offered twice", ("3" in ids, again["skipped_filed"]), (False, 1))
    check("intake: a resolved item that came back links its old ticket", ids.get("5"), "P-2")

    def broken(method, path, body):
        raise SourceError("Sentry answered HTTP 429 for /organizations/acme/issues/")
    b = collect(cfg, top, {}, sentry_fetch=broken, now=now)["sources"][0]
    check("intake: a rate-limited Sentry gives ok=false and no items", (b["ok"], b["items"]), (False, []))
    whole_org = collect({"sentry": {"org": "acme"}}, top, {}, sentry_fetch=fetch, now=now)["sources"][0]
    check("intake: no projects named means no org-wide read", (whole_org["ok"], "projects is empty" in (whole_org["error"] or "")), (False, True))

    old_env = os.environ.pop("FLEET_SELFTEST_SENTRY", None)
    tok, err = sentry_token({"token_env": "FLEET_SELFTEST_SENTRY"})
    check("intake: no token is a clear error", (tok, (err or "").startswith("no token")), (None, True))
    tf = os.path.join(top, "tok")
    with open(tf, "w") as f:
        f.write("abc\n")
    os.chmod(tf, 0o644)
    tok, warn = sentry_token({"token_env": "FLEET_SELFTEST_SENTRY", "token_file": tf})
    check("intake: token file read, loose mode warned", (tok, "chmod 600" in (warn or "")), ("abc", True))
    if old_env is not None:
        os.environ["FLEET_SELFTEST_SENTRY"] = old_env

    with open(os.path.join(top, "package.json"), "w") as f:
        f.write('{"dependencies": {"@sentry/angular": "10.0.0"}}')
    check("intake: SDK with no sentry block warns", bool(sdk_without_config({}, top)), True)
    check("intake: SDK with a sentry block is quiet", sdk_without_config(cfg, top), None)

    def runner_of(code, out, err=""):
        return lambda c: SimpleNamespace(returncode=code, stdout=out, stderr=err)
    good = json.dumps({"items": [{"external_id": "a1", "title": "Disk full on db", "severity": "high",
                                  "evidence": "seen by ops@example.com"},
                                 {"external_id": "a2", "title": "x", "severity": "weird"}, {"title": "no id"}]})
    ccfg = {"fleet": {"intake_sources": [{"name": "uptime", "command": "check-uptime", "max_per_run": 5}]}}
    r = collect(ccfg, top, {}, runner=runner_of(0, good))["sources"][0]
    check("intake: command items parsed, bad ones dropped, unknown severity -> medium",
          [(i["external_id"], i["severity"]) for i in r["items"]], [("a1", "high"), ("a2", "medium")])
    check("intake: command evidence scrubbed", "ops@example.com" in r["items"][0]["evidence"], False)
    r = collect(ccfg, top, {}, runner=runner_of(0, "not json"))["sources"][0]
    check("intake: command with bad JSON is ok=false", (r["ok"], r["error"]), (False, "command output is not JSON"))
    r = collect(ccfg, top, {}, runner=runner_of(3, "", "boom key=supersecret"))["sources"][0]
    check("intake: failing command is ok=false, secret not echoed", (r["ok"], "supersecret" in (r["error"] or "")), (False, False))

    calls.clear()
    home = tempfile.mkdtemp(prefix="fleetintake-home-")
    rc = cmd_resolve(cfg, top, home, "proj", "sentry", "3", "abc123", "P-1", sentry_fetch=fetch)
    put = next((b for m, p, b in calls if m == "PUT"), None)
    check("intake: resolve sends resolved in the release", (rc, put), (0, {"status": "resolved", "statusDetails": {"inRelease": "abc123"}}))
    check("intake: resolve records state", read_state(home, "proj")["sentry"]["3"]["status"], "resolved")
    lines = []
    cmd_check(cfg, top, sentry_fetch=fetch, out=lines.append)
    check("intake: check names org, projects and env", lines[0].startswith("ok   sentry acme/web,api env=prod"), True)


if __name__ == "__main__":
    sys.exit(main())
