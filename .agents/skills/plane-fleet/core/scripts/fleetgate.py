#!/usr/bin/env python3
"""fleet gate-stamp: let a group PR merge on the PM's local gate instead of waiting for CI
jobs that re-run exactly the same checks.

  fleet gate-stamp post --cwd REPO --sha SHA --log FILE [--duration SEC]
      Only after the pre-push gate passed on exactly that commit: HEAD must be SHA, the
      tracked tree clean, and the log must match quality.pre_push_success_regex (and not
      quality.pre_push_skip_regex). Then it posts the commit status `local-gate` = success
      on SHA, naming the machine and the gate's duration.
  fleet gate-stamp check --pr N [--cwd REPO] [--json]
      Says whether the PR head carries `local-gate` success, and which other checks are
      still pending or failing once the covered ones are set aside. Exit 0 only when the
      stamp is there and every non-covered check passed or was skipped; 1 otherwise.
  fleet gate-stamp selftest

Config:
  ci.covered_by_local_gate: ["Nx Affected"]   CI check names the pre-push gate fully covers.
                                              Empty (the default) = the feature is off.
  quality.pre_push_success_regex              default: ^pre-push exit 0 at <sha>$ (multiline);
                                              <sha> is replaced by the full SHA. Write it from
                                              a wrapper: `{ <gate>; echo "pre-push exit $? at $(git rev-parse HEAD)"; }`
  quality.pre_push_skip_regex                 optional: a log that matches it is a gate that skipped
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONTEXT = "local-gate"
DEFAULT_OK = r"(?m)^pre-push exit 0 at <sha>\s*$"
PASS, SKIP, FAILB, CANCEL = "pass", "skipping", "fail", "cancel"


class Fail(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def run(argv, cwd=None):
    return subprocess.run(argv, capture_output=True, text=True, cwd=cwd)


def settings(cwd):
    sys.path.insert(0, HERE)
    import fleetctl
    cwd = os.path.abspath(cwd or os.getcwd())
    cfg = fleetctl.project_config(cwd) or {}
    ci, qual, git = cfg.get("ci") or {}, cfg.get("quality") or {}, cfg.get("git") or {}
    return {"cwd": cwd, "covered": list(ci.get("covered_by_local_gate") or []),
            "ok_re": qual.get("pre_push_success_regex") or DEFAULT_OK, "skip_re": qual.get("pre_push_skip_regex"),
            "trunk": git.get("trunk"), "runner": run, "host": socket.gethostname().split(".")[0]}


def dur(sec):
    sec = int(sec)
    return f"{sec // 60}m{sec % 60:02d}s" if sec >= 60 else f"{sec}s"


# ---------------------------------------------------------------- post
def post(s, sha, log, duration=None):
    if not s["covered"]:
        raise Fail("gate-stamp: off (ci.covered_by_local_gate is empty)", 3)
    g = lambda *a: s["runner"](["git", "-C", s["cwd"], *a])
    r = g("rev-parse", "--verify", f"{sha}^{{commit}}")
    if r.returncode != 0:
        raise Fail(f"gate-stamp: unknown commit {sha}")
    full = r.stdout.strip()
    head = g("rev-parse", "HEAD").stdout.strip()
    if head != full:
        raise Fail(f"gate-stamp: HEAD is {head[:12]}, not {full[:12]}; the gate must have run on the stamped commit")
    dirty = g("status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        raise Fail("gate-stamp: the tracked tree has changes, so the gate did not run on exactly this commit:\n" + dirty)
    try:
        text = open(log, errors="replace").read()
        st = os.stat(log)
    except OSError as e:
        raise Fail(f"gate-stamp: cannot read the gate log: {e}")
    if s["skip_re"] and re.search(s["skip_re"], text):
        raise Fail("gate-stamp: the log says the gate skipped its checks; nothing to stamp")
    if not re.search(s["ok_re"].replace("<sha>", full), text):
        raise Fail(f"gate-stamp: the log shows no success for {full[:12]} (pattern {s['ok_re']})")
    ct = g("show", "-s", "--format=%ct", full).stdout.strip()
    if ct.isdigit() and st.st_mtime < int(ct):
        raise Fail("gate-stamp: the log is older than the commit")
    if duration is None:
        born = getattr(st, "st_birthtime", None)
        duration = (st.st_mtime - born) if born else None
    desc = f"pre-push gate passed on {s['host']}" + (f" in {dur(duration)}" if duration else "")
    r = s["runner"](["gh", "api", "-X", "POST", f"repos/{{owner}}/{{repo}}/statuses/{full}",
                     "-f", "state=success", "-f", f"context={CONTEXT}", "-f", f"description={desc[:140]}"], cwd=s["cwd"])
    if r.returncode != 0:
        raise Fail(f"gate-stamp: gh api failed: {(r.stderr or r.stdout).strip()}")
    print(f"gate-stamp: {CONTEXT} = success on {full[:12]} ({desc})")
    return full


# ---------------------------------------------------------------- check
def gh_json(s, argv):
    r = s["runner"](["gh", *argv], cwd=s["cwd"])
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise Fail(f"gate-stamp: gh {' '.join(argv[:3])} failed: {(r.stderr or r.stdout).strip()}", 2)


RUN_ID = re.compile(r"/actions/runs/(\d+)")
FAIL_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}


def run_id(url):
    m = RUN_ID.search(url or "")
    return int(m.group(1)) if m else None


def bucket_of(item):
    """Bucket for a statusCheckRollup CheckRun, in `gh pr checks` terms."""
    if (item.get("status") or "").upper() != "COMPLETED":
        return "pending", (item.get("status") or "PENDING").upper()
    c = (item.get("conclusion") or "").upper()
    if c == "SUCCESS":
        return PASS, c
    if c in ("SKIPPED", "NEUTRAL"):
        return SKIP, c
    if c == "CANCELLED":
        return CANCEL, c
    return FAILB, c or "FAILURE"


def newest_runs(checks, rollup):
    """`gh pr checks` keeps one row per check name, and it can keep a re-run attempt of an
    old workflow run (whose event still carries the old PR title, say) over a newer run of
    the same workflow. GitHub's merge state uses the newest run, so do the same: for each
    name, the CheckRun from the highest workflow run id wins."""
    best = {}
    for it in rollup or []:
        rid = run_id(it.get("detailsUrl"))
        if it.get("__typename") not in (None, "CheckRun") or not it.get("name") or rid is None:
            continue
        if it["name"] not in best or rid > best[it["name"]][0]:
            best[it["name"]] = (rid, it)
    out = []
    for c in checks:
        mine, top = run_id(c.get("link")), best.get(c.get("name"))
        if top and mine is not None and top[0] > mine:
            b, state = bucket_of(top[1])
            c = {**c, "bucket": b, "state": state, "link": top[1].get("detailsUrl"), "superseded": mine}
        out.append(c)
    return out


def check(s, pr):
    if not s["covered"]:
        raise Fail("gate-stamp: off (ci.covered_by_local_gate is empty)", 3)
    view = gh_json(s, ["pr", "view", str(pr), "--json", "headRefOid,baseRefName,state,statusCheckRollup"])
    sha, base = view.get("headRefOid", ""), view.get("baseRefName")
    st = gh_json(s, ["api", f"repos/{{owner}}/{{repo}}/commits/{sha}/status"])
    stamp = next((x for x in st.get("statuses") or [] if x.get("context") == CONTEXT), None)
    checks = newest_runs(gh_json(s, ["pr", "checks", str(pr), "--json", "name,bucket,state,link"]),
                         view.get("statusCheckRollup"))
    covered = [c for c in checks if c.get("name") in s["covered"]]
    others = [c for c in checks if c.get("name") not in s["covered"] and c.get("name") != CONTEXT]
    covered_stopped = any(c.get("bucket") in (CANCEL, FAILB) for c in covered)
    problems = []
    if s["trunk"] and base != s["trunk"]:
        problems.append(f"base is {base}, not the trunk {s['trunk']}: only a group PR into the trunk merges on the stamp")
    if not stamp or stamp.get("state") != "success":
        problems.append(f"no {CONTEXT} success on the head {sha[:12]}" + (f" ({stamp.get('state')})" if stamp else ""))
    pending, failing = [], []
    for c in others:
        b = c.get("bucket")
        if b == PASS:
            continue
        if b == SKIP and not covered_stopped:
            continue
        if b == SKIP:
            failing.append(f"{c['name']} (skipped after a covered job stopped; it may depend on it)")
        elif b in (FAILB, CANCEL):
            failing.append(f"{c['name']} ({c.get('state', b).lower()})")
        else:
            pending.append(c["name"])
    if pending:
        problems.append("pending: " + ", ".join(pending))
    if failing:
        problems.append("failing: " + ", ".join(failing))
    res = {"pr": pr, "sha": sha, "base": base, "stamp": bool(stamp and stamp.get("state") == "success"),
           "stamp_description": (stamp or {}).get("description"), "covered": [c["name"] for c in covered],
           "covered_running": [c["name"] for c in covered if c.get("bucket") == "pending"],
           "pending": pending, "failing": failing, "ready": not problems, "problems": problems}
    return res


def show(res, as_json):
    if as_json:
        print(json.dumps(res, indent=1))
        return
    head = f"gate-stamp: PR #{res['pr']} head {res['sha'][:12]}"
    if res["ready"]:
        extra = f"; covered still running: {', '.join(res['covered_running'])} (cancel to free the runner)" if res["covered_running"] else ""
        print(f"{head}: READY ({res['stamp_description'] or CONTEXT}){extra}")
    else:
        print(f"{head}: NOT READY")
        for p in res["problems"]:
            print("  " + p)


# ---------------------------------------------------------------- selftest
def selftest(check_):
    import contextlib, io, shutil, tempfile, time
    d = tempfile.mkdtemp(prefix="fleetgate-selftest-")
    g = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    open(os.path.join(d, "a.txt"), "w").write("1\n"); g("add", "-A"); g("commit", "-qm", "one")
    sha = g("rev-parse", "HEAD").stdout.strip()
    calls, world = [], {"checks": [], "statuses": {}, "base": "develop", "sha": sha, "rollup": []}

    def fake(argv, cwd=None):
        if argv[0] == "git":
            return run(argv, cwd)
        calls.append(argv)
        ok = lambda out: subprocess.CompletedProcess(argv, 0, json.dumps(out), "")
        if argv[1:3] == ["pr", "view"]:
            return ok({"headRefOid": world["sha"], "baseRefName": world["base"], "state": "OPEN",
                       "statusCheckRollup": world["rollup"]})
        if argv[1:3] == ["pr", "checks"]:
            return ok(world["checks"])
        if argv[1] == "api" and argv[-1].endswith("/status"):
            return ok({"statuses": world["statuses"].get(argv[-1].split("/")[-2], [])})
        if argv[1] == "api" and "statuses/" in argv[4]:
            world["statuses"][argv[4].rsplit("/", 1)[1]] = [{"context": CONTEXT, "state": "success",
                                                             "description": argv[-1].split("=", 1)[1]}]
            return ok({})
        return subprocess.CompletedProcess(argv, 1, "", "unexpected")

    s = {"cwd": d, "covered": ["Nx Affected"], "ok_re": DEFAULT_OK, "skip_re": r"\[pre-push\] skipped",
         "trunk": "develop", "runner": fake, "host": "box"}
    log = os.path.join(d, "..", os.path.basename(d) + "-gate.log")

    def attempt(fn, *a, **kw):
        with contextlib.redirect_stdout(io.StringIO()) as o:
            try:
                return fn(*a, **kw), o.getvalue()
            except Fail as e:
                return e, o.getvalue()

    try:
        open(log, "w").write("lint ok\npre-push exit 1 at " + sha + "\n")
        e, _ = attempt(post, s, sha, log)
        check_("gate: a failed gate is not stamped", (isinstance(e, Fail), len(calls)), (True, 0))
        open(log, "w").write("[pre-push] skipped — nothing to gate.\npre-push exit 0 at " + sha + "\n")
        e, _ = attempt(post, s, sha, log)
        check_("gate: a skipped gate is not stamped", isinstance(e, Fail), True)
        open(log, "w").write("pre-push exit 0 at " + "f" * 40 + "\n")
        e, _ = attempt(post, s, sha, log)
        check_("gate: another commit's success is not stamped", isinstance(e, Fail), True)
        open(log, "w").write("all good\npre-push exit 0 at " + sha + "\n")
        open(os.path.join(d, "a.txt"), "w").write("2\n")
        e, _ = attempt(post, s, sha, log)
        check_("gate: a dirty tree is not stamped", "tracked tree" in str(e), True)
        g("checkout", "-q", "a.txt")
        e, _ = attempt(post, s, "HEAD~0", log, 125)
        check_("gate: success on HEAD posts local-gate", (e, calls[-1][4]), (sha, f"repos/{{owner}}/{{repo}}/statuses/{sha}"))
        check_("gate: the description names machine and time", world["statuses"][sha][0]["description"], "pre-push gate passed on box in 2m05s")
        world["checks"] = [{"name": "Nx Affected", "bucket": "pending", "state": "IN_PROGRESS"},
                           {"name": "Security", "bucket": "pass", "state": "SUCCESS"},
                           {"name": "client-e2e", "bucket": "skipping", "state": "SKIPPED"},
                           {"name": CONTEXT, "bucket": "pass", "state": "SUCCESS"}]
        r = check(s, 7)
        check_("gate: covered job still running, rest green = ready", (r["ready"], r["covered_running"]), (True, ["Nx Affected"]))
        world["checks"][1] = {"name": "Security", "bucket": "pending", "state": "QUEUED"}
        check_("gate: a non-covered pending check holds it", check(s, 7)["pending"], ["Security"])
        world["checks"][1] = {"name": "Security", "bucket": "fail", "state": "FAILURE"}
        check_("gate: a non-covered failure holds it", check(s, 7)["ready"], False)
        world["checks"][1] = {"name": "Security", "bucket": "pass", "state": "SUCCESS"}
        world["checks"][0] = {"name": "Nx Affected", "bucket": "cancel", "state": "CANCELLED"}
        check_("gate: a skip after a cancelled covered job is not a pass", check(s, 7)["ready"], False)
        world["checks"][2] = {"name": "client-e2e", "bucket": "pass", "state": "SUCCESS"}
        check_("gate: cancelled covered job, rest passed = ready", check(s, 7)["ready"], True)
        u = lambda rid: f"https://github.com/o/r/actions/runs/{rid}/job/{rid}9"
        world["checks"].append({"name": "Title", "bucket": "fail", "state": "FAILURE", "link": u(100)})
        world["rollup"] = [
            {"__typename": "CheckRun", "name": "Title", "status": "COMPLETED", "conclusion": "FAILURE", "detailsUrl": u(100)},
            {"__typename": "CheckRun", "name": "Title", "status": "COMPLETED", "conclusion": "SUCCESS", "detailsUrl": u(101)}]
        check_("gate: a newer run of a check beats a stale re-run attempt", check(s, 7)["ready"], True)
        world["rollup"][1]["conclusion"] = "FAILURE"
        check_("gate: the newer run failing still holds it", check(s, 7)["failing"], ["Title (failure)"])
        world["rollup"][1].update(status="IN_PROGRESS", conclusion=None)
        check_("gate: the newer run still running is pending", check(s, 7)["pending"], ["Title"])
        world["checks"][-1] = {"name": "Title", "bucket": "fail", "state": "FAILURE", "link": u(101)}
        world["rollup"] = [world["rollup"][0] | {"conclusion": "SUCCESS"},
                           {"__typename": "CheckRun", "name": "Title", "status": "COMPLETED", "conclusion": "FAILURE", "detailsUrl": u(101)}]
        check_("gate: an older passing run never hides a newer failure", check(s, 7)["ready"], False)
        world["checks"].pop(); world["rollup"] = []
        world["sha"] = "e" * 40
        check_("gate: a new head without its own stamp is not ready", check(s, 7)["ready"], False)
        world["sha"], world["base"] = sha, "main"
        check_("gate: a PR into another branch is not ready", check(s, 7)["ready"], False)
        s["covered"] = []
        e, _ = attempt(check, s, 7)
        check_("gate: off exits 3", getattr(e, "code", 0), 3)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        try: os.remove(log)
        except OSError: pass


# ---------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleet gate-stamp")
    ap.add_argument("action", choices=["post", "check", "selftest"])
    ap.add_argument("--cwd"); ap.add_argument("--sha"); ap.add_argument("--log")
    ap.add_argument("--duration", type=float); ap.add_argument("--pr", type=int)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.action == "selftest":
        bad = []
        def check_(name, got, want):
            ok = got == want
            print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": got {got!r}, want {want!r}"))
            if not ok: bad.append(name)
        selftest(check_)
        return 1 if bad else 0
    try:
        s = settings(a.cwd)
        if a.action == "post":
            if not (a.sha and a.log):
                raise Fail("usage: fleet gate-stamp post --cwd REPO --sha SHA --log FILE", 2)
            post(s, a.sha, a.log, a.duration)
            return 0
        if not a.pr:
            raise Fail("usage: fleet gate-stamp check --pr N [--cwd REPO]", 2)
        res = check(s, a.pr)
        show(res, a.json)
        return 0 if res["ready"] else 1
    except Fail as e:
        print(str(e), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
