#!/usr/bin/env python3
"""fleet slot-template: one migrated, seeded Postgres template per schema state, cloned per slot.

Every engineer or tester session used to build its slot database from zero: create, migrate,
seed. That took minutes of every session. Postgres can copy a whole database from a template
in seconds (CREATE DATABASE <db> TEMPLATE <tpl>), so the fleet builds the template once and
each slot clones it.

  fleet slot-template build  [--cwd REPO] [--ref origin/<trunk>] [--force]
      Builds <prefix>_<key12> from the repo at that ref, in a throwaway worktree, with the
      configured build commands. The key hashes the files under key_paths (migrations, seed)
      and the build commands, not the commit, so a template is reused until they change.
      A lock stops two builds at once (exit 75). Older templates beyond `keep` are dropped.
  fleet slot-template clone <slot> [--test] [--cwd REPO] [--ref HEAD] [--force]
      Drops the slot's DB (and its test DB with --test) and clones it from the ready template
      that matches the worktree's key. Exit 3 when there is none: run the normal recipe.
      Only slot DBs named in fleet.slots are touched, never the shared row's.
  fleet slot-template status [--cwd REPO] [--json]
  fleet slot-template selftest

Config, under fleet.slot_db_template in .plane/config.json or the user override:
  {"enabled": true,
   "name_prefix": "<shared slot db, or the project>_tpl",
   "build": ["pnpm install --frozen-lockfile", "pnpm db:migrate", "pnpm db:seed"],
   "admin_url": "postgresql://user:pass@localhost:5432/postgres",   or "admin_url_env": "VAR"
   "psql": ["psql"],             the psql command; e.g. ["docker", "exec", "<container>", "psql"]
   "url_template": "postgresql://user:pass@localhost:5432/<db>",    the URL the build commands use
   "key_paths": ["prisma/"],     default fleet.schema_paths
   "keep": 2}
Build commands run with bash in the throwaway worktree, DATABASE_URL set to the template's URL,
and these placeholders filled: <db> <url> <repo> (the checkout given by --cwd) <dir> (the
worktree) <sha>. Python stdlib only; every database call goes through psql.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_HOME = os.environ.get("PLANE_FLEET_HOME") or os.path.expanduser("~/.config/plane-fleet")
NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
MARK = "fleet-slot-template"
OFF, NONE, LOCKED = 3, 3, 75
BUSY = "is being accessed by other users"


class Fail(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- settings
def settings(cwd):
    sys.path.insert(0, HERE)
    import fleetctl
    cwd = os.path.abspath(cwd or os.getcwd())
    full = fleetctl.project_config(cwd) or {}
    cfg = full.get("fleet") or {}
    t = cfg.get("slot_db_template") or {}
    project = fleetctl.project_of(cwd) or os.path.basename(cwd)
    slots = cfg.get("slots") or {}
    shared = slots.get("shared") or {}
    prefix = t.get("name_prefix") or f"{shared.get('db') or re.sub(r'[^a-z0-9_]', '_', project.lower())}_tpl"
    admin = t.get("admin_url") or (os.environ.get(t["admin_url_env"]) if t.get("admin_url_env") else None)
    psql = t.get("psql") or ["psql"]
    if isinstance(psql, str):
        psql = shlex.split(psql)
    url_t = t.get("url_template") or (re.sub(r"(//[^/]*/)[^?]*", r"\1<db>", admin, count=1) if admin else None)
    tmp = ((cfg.get("tool_caches") or {}).get("tmpdir")) or tempfile.gettempdir()
    git = full.get("git") or {}
    return {
        "enabled": bool(t.get("enabled")), "prefix": prefix, "admin_url": admin, "psql": psql,
        "url_template": url_t, "build": list(t.get("build") or []), "keep": int(t.get("keep") or 2),
        "key_paths": list(t.get("key_paths") or cfg.get("schema_paths") or []), "slots": slots,
        "project": project, "cwd": cwd, "tmp": os.path.expanduser(os.path.expandvars(tmp)),
        "trunk": f"{git.get('remote') or 'origin'}/{git.get('trunk') or 'main'}",
        "state": os.path.join(STATE_HOME, "slot-template"), "runner": run, "sleep": time.sleep,
    }


def need(s):
    if not s["enabled"]:
        raise Fail("slot-template is off (fleet.slot_db_template.enabled); run the normal slot recipe", OFF)
    if not s["admin_url"]:
        raise Fail("slot-template: no admin URL (fleet.slot_db_template.admin_url or admin_url_env)", OFF)
    if not s["key_paths"]:
        raise Fail("slot-template: no key_paths and no fleet.schema_paths; nothing to key the template on", OFF)


# ---------------------------------------------------------------- postgres
def q(name):
    if not NAME_RE.match(name or ""):
        raise Fail(f"slot-template: refusing database name {name!r} (lowercase letters, digits and _ only)", 2)
    return f'"{name}"'


def lit(v):
    return "'" + str(v).replace("'", "''") + "'"


def psql(s, sql, check=True):
    r = s["runner"](s["psql"] + [s["admin_url"], "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1", "-c", sql])
    if check and r.returncode != 0:
        raise Fail(f"psql failed: {sql}\n{(r.stderr or r.stdout).strip()}")
    return r


def templates(s):
    """{name: {"state": ready|building, "key":..., "sha":..., "built":...}} for every db under the prefix."""
    pre = s["prefix"] + "_"
    r = psql(s, "select datname || '|' || coalesce(shobj_description(oid, 'pg_database'), '') from pg_database "
                f"where left(datname, {len(pre)}) = {lit(pre)} order by datname")
    out = {}
    for line in (r.stdout or "").splitlines():
        name, _, comment = line.partition("|")
        if not name:
            continue
        info = {"state": "unknown"}
        if comment.startswith(MARK + " "):
            parts = comment.split()
            info["state"] = parts[1]
            info.update(p.split("=", 1) for p in parts[2:] if "=" in p)
        out[name] = info
    return out


def drop_template(s, name):
    psql(s, f"ALTER DATABASE {q(name)} WITH IS_TEMPLATE false ALLOW_CONNECTIONS true", check=False)
    r = psql(s, f"DROP DATABASE IF EXISTS {q(name)}", check=False)
    if r.returncode != 0:
        print(f"slot-template: could not drop {name} ({(r.stderr or '').strip()}); left in place", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------- key
def key_of(s, ref):
    r = s["runner"](["git", "-C", s["cwd"], "ls-tree", "-r", ref, "--", *s["key_paths"]])
    if r.returncode != 0:
        raise Fail(f"slot-template: git ls-tree {ref} failed: {r.stderr.strip()}")
    if not r.stdout.strip():
        raise Fail(f"slot-template: nothing under {s['key_paths']} at {ref}; check key_paths")
    h = hashlib.sha256(r.stdout.encode())
    h.update(json.dumps(s["build"]).encode())
    return h.hexdigest()


def rev(s, ref):
    r = s["runner"](["git", "-C", s["cwd"], "rev-parse", "--verify", f"{ref}^{{commit}}"])
    if r.returncode != 0:
        raise Fail(f"slot-template: unknown ref {ref}")
    return r.stdout.strip()


def ready_for(s, key):
    for name, info in templates(s).items():
        if info.get("state") == "ready" and info.get("key") == key:
            return name, info
    return None, None


# ---------------------------------------------------------------- lock
class Lock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.f = open(self.path, "a+")
        try:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            pass
        except OSError:
            self.f.close()
            raise Fail(f"slot-template: another build holds {self.path}; it will finish the template", LOCKED)
        self.f.seek(0); self.f.truncate(); self.f.write(f"{os.getpid()} {socket.gethostname()}\n"); self.f.flush()
        return self

    def __exit__(self, *a):
        self.f.close()


# ---------------------------------------------------------------- build
def fill(cmd, **kv):
    for k, v in kv.items():
        cmd = cmd.replace(f"<{k}>", v)
    return cmd


def build(s, ref=None, force=False):
    need(s)
    if not s["build"]:
        raise Fail("slot-template: fleet.slot_db_template.build is empty", OFF)
    ref = ref or s["trunk"]
    if "/" in ref and not ref.startswith("refs/"):
        remote, _, branch = ref.partition("/")
        s["runner"](["git", "-C", s["cwd"], "fetch", "-q", remote, branch])
    sha = rev(s, ref)
    key = key_of(s, ref)
    name = f"{s['prefix']}_{key[:12]}"
    q(name)
    with Lock(os.path.join(s["state"], f"{s['project']}.lock")):
        have = templates(s)
        if name in have and have[name].get("state") == "ready" and not force:
            print(f"slot-template: {name} is ready already (key {key[:12]}, built from {have[name].get('sha', '?')[:12]})")
            prune(s, keep_name=name)
            return name
        if name in have:
            drop_template(s, name)
        t0 = time.time()
        psql(s, f"CREATE DATABASE {q(name)}")
        psql(s, f"COMMENT ON DATABASE {q(name)} IS {lit(f'{MARK} building key={key} sha={sha}')}")
        d = os.path.join(s["tmp"], f"fleet-tpl-{s['project']}-{key[:12]}")
        if os.path.exists(d):
            s["runner"](["git", "-C", s["cwd"], "worktree", "remove", "--force", d])
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(s["tmp"], exist_ok=True)
        r = s["runner"](["git", "-C", s["cwd"], "worktree", "add", "-q", "--detach", d, sha])
        if r.returncode != 0:
            drop_template(s, name)
            raise Fail(f"slot-template: git worktree add failed: {r.stderr.strip()}")
        os.makedirs(s["state"], exist_ok=True)
        log = os.path.join(s["state"], f"{s['project']}-build.log")
        url = s["url_template"].replace("<db>", name)
        env = {**os.environ, "DATABASE_URL": url, "FLEET_TEMPLATE_DB": name}
        try:
            with open(log, "w") as lf:
                for raw in s["build"]:
                    cmd = fill(raw, db=name, url=url, repo=s["cwd"], dir=d, sha=sha)
                    lf.write(f"$ {cmd}\n"); lf.flush()
                    p = subprocess.run(["bash", "-c", cmd], cwd=d, env=env, stdout=lf, stderr=subprocess.STDOUT)
                    if p.returncode != 0:
                        drop_template(s, name)
                        tail = open(log).read().splitlines()[-15:]
                        raise Fail(f"slot-template: build step failed (exit {p.returncode}): {cmd}\n"
                                   + "\n".join("  " + l for l in tail) + f"\nfull log: {log}")
            psql(s, "select pg_terminate_backend(pid) from pg_stat_activity "
                    f"where datname = {lit(name)} and pid <> pg_backend_pid()", check=False)
            built = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            psql(s, f"COMMENT ON DATABASE {q(name)} IS {lit(f'{MARK} ready key={key} sha={sha} built={built}')}")
            psql(s, f"ALTER DATABASE {q(name)} WITH ALLOW_CONNECTIONS false IS_TEMPLATE true")
        finally:
            s["runner"](["git", "-C", s["cwd"], "worktree", "remove", "--force", d])
            shutil.rmtree(d, ignore_errors=True)
        save_state(s)
        print(f"slot-template: {name} ready (key {key[:12]}, sha {sha[:12]}, {time.time() - t0:.0f}s)")
        prune(s, keep_name=name)
        return name


def prune(s, keep_name):
    have = templates(s)
    ready = sorted((n for n, i in have.items() if i.get("state") == "ready"),
                   key=lambda n: have[n].get("built", ""), reverse=True)
    keep = set(ready[:max(1, s["keep"])]) | {keep_name}
    for n, i in have.items():          # the caller holds the lock, so a "building" one is a dead build's leftover
        if n not in keep and drop_template(s, n):
            print(f"slot-template: dropped {'old' if i.get('state') == 'ready' else 'unfinished'} template {n}")
    save_state(s)


def save_state(s):
    try:
        os.makedirs(s["state"], exist_ok=True)
        with open(os.path.join(s["state"], f"{s['project']}.json"), "w") as f:
            json.dump({"prefix": s["prefix"], "templates": templates(s)}, f, indent=1)
    except Exception:
        pass


# ---------------------------------------------------------------- clone
def protected(s):
    shared = (s["slots"] or {}).get("shared") or {}
    names = {"postgres", "template0", "template1"}
    if shared.get("db"):
        names |= {shared["db"], shared["db"] + "_test"}
    if shared.get("db_test"):
        names.add(shared["db_test"])
    return names


def slot_dbs(s, slot, test):
    if slot == "shared":
        raise Fail("slot-template: never the shared row", 2)
    row = (s["slots"] or {}).get(slot)
    if not isinstance(row, dict) or not row.get("db"):
        raise Fail(f"slot-template: {slot!r} is not a slot in fleet.slots (slots: "
                   f"{', '.join(k for k in (s['slots'] or {}) if k != 'shared') or 'none'})", 2)
    dbs = [row["db"]] + ([row.get("db_test") or row["db"] + "_test"] if test else [])
    for db in dbs:
        q(db)
        if db in protected(s) or db.startswith(s["prefix"] + "_"):
            raise Fail(f"slot-template: refusing {db}: it is the shared database or a template", 2)
    return dbs


def clone(s, slot, test=False, ref="HEAD", force=False):
    need(s)
    dbs = slot_dbs(s, slot, test)
    key = key_of(s, ref)
    tpl, info = ready_for(s, key)
    if not tpl:
        ready = [n for n, i in templates(s).items() if i.get("state") == "ready"]
        raise Fail(f"slot-template: no ready template for this worktree (key {key[:12]}; ready: "
                   f"{', '.join(ready) or 'none'}). Run the normal recipe (migrate, seed), "
                   f"or `fleet slot-template build` if trunk changed.", NONE)
    for db in dbs:
        r = psql(s, f"DROP DATABASE IF EXISTS {q(db)}" + (" WITH (FORCE)" if force else ""), check=False)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip()
            if BUSY in msg:
                raise Fail(f"slot-template: {db} still has connections. Stop the slot's server and tests "
                           f"first, or pass --force to end them.\n{msg}")
            raise Fail(f"slot-template: could not drop {db}: {msg}")
        for attempt in range(4):
            r = psql(s, f"CREATE DATABASE {q(db)} TEMPLATE {q(tpl)}", check=False)
            if r.returncode == 0:
                break
            msg = (r.stderr or r.stdout).strip()
            if BUSY not in msg:
                raise Fail(f"slot-template: could not create {db} from {tpl}: {msg}")
            s["sleep"](2)
        else:
            raise Fail(f"slot-template: template {tpl} has open connections, so Postgres will not copy it. "
                       f"Built templates refuse connections; a superuser session is on it. Find it with:\n"
                       f"  select pid, usename, application_name from pg_stat_activity where datname = '{tpl}';\n"
                       f"Run the normal recipe meanwhile.")
    print(f"slot-template: {', '.join(dbs)} cloned from {tpl} (key {key[:12]}, built from "
          f"{info.get('sha', '?')[:12]} at {info.get('built', '?')}). Skip migrate and seed.")
    return tpl


# ---------------------------------------------------------------- status
def status(s, as_json=False):
    rows = templates(s) if s["enabled"] and s["admin_url"] else {}
    keys = {}
    for ref in ("HEAD", s["trunk"]):
        try:
            keys[ref] = key_of(s, ref)
        except Fail:
            keys[ref] = None
    if as_json:
        print(json.dumps({"enabled": s["enabled"], "prefix": s["prefix"], "templates": rows,
                          "keys": keys}, indent=1))
        return 0
    print(f"slot-template: {'on' if s['enabled'] else 'off'} · prefix {s['prefix']} · keep {s['keep']}")
    for ref, k in keys.items():
        hit = next((n for n, i in rows.items() if k and i.get("key") == k and i.get("state") == "ready"), None)
        print(f"  {ref}: key {k[:12] if k else '-'} -> {hit or 'no ready template'}")
    for n, i in rows.items():
        print(f"  {n}: {i.get('state')} · sha {i.get('sha', '?')[:12]} · built {i.get('built', '-')}")
    return 0


# ---------------------------------------------------------------- selftest
class FakePG:
    """Answers the psql calls this file makes, from a dict of databases."""

    def __init__(self):
        self.dbs = {"postgres": {}, "app_dev": {}, "app_slot_a": {}, "app_slot_a_test": {}}
        self.busy = set()
        self.log = []

    def __call__(self, argv, **kw):
        if argv[0] == "git":
            return subprocess.run(argv, capture_output=True, text=True, **kw)
        sql = argv[-1]
        self.log.append(sql)
        ok = subprocess.CompletedProcess(argv, 0, "", "")
        err = lambda m: subprocess.CompletedProcess(argv, 1, "", "ERROR:  " + m)
        m = re.match(r'CREATE DATABASE "(\w+)"(?: TEMPLATE "(\w+)")?$', sql)
        if m:
            if m.group(1) in self.dbs:
                return err("already exists")
            if m.group(2) and m.group(2) in self.busy:
                return err(f'source database "{m.group(2)}" {BUSY}')
            self.dbs[m.group(1)] = dict(self.dbs.get(m.group(2) or "", {}), comment="", copied_from=m.group(2), is_template=False)
            return ok
        m = re.match(r'DROP DATABASE IF EXISTS "(\w+)"( WITH \(FORCE\))?$', sql)
        if m:
            if m.group(1) in self.busy and not m.group(2):
                return err(f'database "{m.group(1)}" {BUSY}')
            if self.dbs.get(m.group(1), {}).get("is_template"):
                return err("cannot drop a template database")
            self.dbs.pop(m.group(1), None)
            return ok
        m = re.match(r'COMMENT ON DATABASE "(\w+)" IS \'(.*)\'$', sql)
        if m:
            self.dbs[m.group(1)]["comment"] = m.group(2)
            return ok
        m = re.match(r'ALTER DATABASE "(\w+)" WITH (.*)$', sql)
        if m:
            if m.group(1) in self.dbs:
                self.dbs[m.group(1)]["is_template"] = "IS_TEMPLATE true" in m.group(2)
            return ok
        m = re.search(r"left\(datname, \d+\) = '(\w+)'", sql)
        if m:
            out = "".join(f"{n}|{d.get('comment', '')}\n" for n, d in sorted(self.dbs.items()) if n.startswith(m.group(1)))
            return subprocess.CompletedProcess(argv, 0, out, "")
        if "pg_terminate_backend" in sql:
            return ok
        return err("fake psql: unexpected sql " + sql)


def selftest(check):
    d = tempfile.mkdtemp(prefix="fleettpl-selftest-")
    repo = os.path.join(d, "repo")
    os.makedirs(os.path.join(repo, "db", "migrations"))
    g = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    open(os.path.join(repo, "db", "migrations", "001.sql"), "w").write("create table a();\n")
    open(os.path.join(repo, "app.txt"), "w").write("v1\n")
    g("add", "-A"); g("commit", "-qm", "one")
    pg = FakePG()
    s = {"enabled": True, "prefix": "app_dev_tpl", "admin_url": "postgresql://u@h/postgres", "psql": ["psql"],
         "url_template": "postgresql://u@h/<db>", "build": ["echo '<db> <url> <sha>' > \"$FLEET_TEMPLATE_DB.txt\"",
                                                           "test \"$DATABASE_URL\" = '<url>'"],
         "keep": 1, "key_paths": ["db/"], "cwd": repo, "project": "st", "tmp": os.path.join(d, "tmp"),
         "trunk": "HEAD", "state": os.path.join(d, "state"), "runner": pg, "sleep": lambda n: None,
         "slots": {"shared": {"db": "app_dev"}, "A": {"db": "app_slot_a"}, "Z": {"db": "app_dev_tpl_x"}}}
    import contextlib, io

    def quiet(fn, *a, **kw):
        with contextlib.redirect_stdout(io.StringIO()) as o, contextlib.redirect_stderr(io.StringIO()):
            try:
                return fn(*a, **kw), o.getvalue()
            except Fail as e:
                return e, o.getvalue()

    try:
        k1 = key_of(s, "HEAD")
        name, _ = quiet(build, s, "HEAD")
        check("template: build names it by key", name, f"app_dev_tpl_{k1[:12]}")
        info = templates(s).get(name, {})
        check("template: marked ready with its key", (info.get("state"), info.get("key")), ("ready", k1))
        check("template: closed to connections", pg.dbs[name].get("is_template"), True)
        check("template: throwaway worktree removed", os.path.exists(os.path.join(s["tmp"], f"fleet-tpl-st-{k1[:12]}")), False)
        again, out = quiet(build, s, "HEAD")
        check("template: a second build reuses it", ("ready already" in out, again), (True, name))
        open(os.path.join(repo, "app.txt"), "w").write("v2\n"); g("commit", "-qam", "code only")
        check("template: a code-only commit keeps the key", key_of(s, "HEAD"), k1)
        t, out = quiet(clone, s, "A", test=True)
        check("clone: slot and test DB come from the template",
              (t, pg.dbs["app_slot_a"].get("copied_from"), pg.dbs["app_slot_a_test"].get("copied_from")), (name, name, name))
        check("clone: prints the template used", name in out, True)
        e, _ = quiet(clone, s, "shared")
        check("clone: refuses the shared row", getattr(e, "code", 0), 2)
        e, _ = quiet(clone, s, "nope")
        check("clone: refuses a name not in fleet.slots", getattr(e, "code", 0), 2)
        e, _ = quiet(clone, s, "Z")
        check("clone: refuses a template's name", getattr(e, "code", 0), 2)
        pg.busy.add("app_slot_a")
        e, _ = quiet(clone, s, "A")
        check("clone: a busy slot DB says stop the server", "Stop the slot's server" in str(e), True)
        t, _ = quiet(clone, s, "A", force=True)
        check("clone: --force drops it anyway", t, name)
        pg.busy = {name}
        e, _ = quiet(clone, s, "A", force=True)
        check("clone: a template with connections gets a clear message", "has open connections" in str(e), True)
        pg.busy = set()
        open(os.path.join(repo, "db", "migrations", "002.sql"), "w").write("create table b();\n")
        g("add", "-A"); g("commit", "-qm", "migration")
        e, _ = quiet(clone, s, "A")
        check("clone: a new migration with no template exits 3", getattr(e, "code", 0), NONE)
        name2, _ = quiet(build, s, "HEAD")
        check("template: a new migration builds a new one", name2 != name and name2 in pg.dbs, True)
        check("template: keep=1 drops the older one", name in pg.dbs, False)
        s["build"] = ["false"]
        open(os.path.join(repo, "db", "migrations", "003.sql"), "w").write("x\n"); g("add", "-A"); g("commit", "-qm", "m3")
        e, _ = quiet(build, s, "HEAD")
        check("template: a failed build leaves no database", (getattr(e, "code", 0), sum(n.startswith("app_dev_tpl_") for n in pg.dbs)), (1, 1))
        with Lock(os.path.join(s["state"], "st.lock")):
            e, _ = quiet(build, s, "HEAD")
        check("template: a held lock exits 75", getattr(e, "code", 0), LOCKED)
        s["enabled"] = False
        e, _ = quiet(clone, s, "A")
        check("template: off exits 3", getattr(e, "code", 0), OFF)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleet slot-template")
    ap.add_argument("action", choices=["build", "clone", "status", "selftest"])
    ap.add_argument("slot", nargs="?")
    ap.add_argument("--cwd"); ap.add_argument("--ref"); ap.add_argument("--test", action="store_true")
    ap.add_argument("--force", action="store_true"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.action == "selftest":
        bad = []
        def check(name, got, want):
            ok = got == want
            print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": got {got!r}, want {want!r}"))
            if not ok: bad.append(name)
        selftest(check)
        return 1 if bad else 0
    try:
        s = settings(a.cwd)
        if a.action == "build":
            build(s, a.ref, a.force)
        elif a.action == "clone":
            if not a.slot:
                raise Fail("usage: fleet slot-template clone <slot> [--test] [--cwd REPO]", 2)
            clone(s, a.slot, a.test, a.ref or "HEAD", a.force)
        else:
            return status(s, a.json)
    except Fail as e:
        print(str(e), file=sys.stderr)
        return e.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
