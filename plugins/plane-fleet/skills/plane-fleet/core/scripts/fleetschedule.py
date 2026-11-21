#!/usr/bin/env python3
"""Unattended fleet runs on a timer (core/references/unattended.md).

  fleet schedule install --every 2h [--cwd DIR]   a launchd agent (macOS) or a crontab line (Linux)
  fleet schedule remove [--cwd DIR]               take it out again
  fleet schedule status [--cwd DIR]               installed or not, paused or not, the last runs
  fleet schedule pause | resume [--cwd DIR]       skip runs without uninstalling
  fleet schedule run-once [--cwd DIR]             what the timer calls: one unattended PM run

run-once starts fleet.unattended.command in the repo with FLEET_UNATTENDED=1, so the
unattended guard hook is on for that run. It does nothing when the schedule is paused, when
another unattended run of the same project holds the lock, or when an attended PM session wrote
its heartbeat in the last fleet.unattended.attended_grace_minutes. It stops the run after
fleet.unattended.max_hours and calls fleet.alert_command when the run fails or times out.
"""
import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.join(HERE, "fleet")
DEFAULTS = {"max_hours": 3, "attended_grace_minutes": 30, "allow": []}
LABEL_PREFIX = "dev.plane-fleet.unattended"
CRON_TAG = "# plane-fleet unattended"


def fleetctl():
    sys.path.insert(0, HERE)
    import fleetctl as fc
    return fc


def load(cwd):
    fc = fleetctl()
    cwd = os.path.abspath(cwd or os.getcwd())
    top = fc.git(cwd, "rev-parse", "--show-toplevel") or cwd
    cfg = fc.project_config(cwd) or {}
    return cfg, top, fc.project_of(cwd), fc.STATE_HOME


def unattended_cfg(cfg):
    return {**DEFAULTS, **(((cfg.get("fleet") or {}).get("unattended")) or {})}


def paths(home, project):
    d = os.path.join(home, "unattended", project or "default")
    return {"dir": d, "lock": os.path.join(d, "run.lock"), "paused": os.path.join(d, "paused"),
            "runs": os.path.join(d, "runs.jsonl"), "heartbeat": os.path.join(home, "state", f"pm-heartbeat-{project}")}


def parse_every(text):
    m = re.fullmatch(r"\s*(\d+)\s*([mh])\s*", text or "")
    if not m:
        raise SystemExit("--every takes minutes or hours, like 45m or 2h")
    n = int(m.group(1)) * (60 if m.group(2) == "h" else 1)
    if n < 15:
        raise SystemExit("--every must be at least 15m: a run needs time to start and to finish")
    return n


def label(project):
    return f"{LABEL_PREFIX}.{re.sub(r'[^A-Za-z0-9_.-]', '-', project or 'default')}"


def plist(project, top, minutes, log_dir):
    """A launchd agent that calls `fleet schedule run-once` in the repo every <minutes>."""
    args = "".join(f"\n      <string>{a}</string>" for a in (FLEET, "schedule", "run-once", "--cwd", top))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>{label(project)}</string>
    <key>ProgramArguments</key>
    <array>{args}
    </array>
    <key>WorkingDirectory</key><string>{top}</string>
    <key>StartInterval</key><integer>{minutes * 60}</integer>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>{os.path.join(log_dir, "launchd.log")}</string>
    <key>StandardErrorPath</key><string>{os.path.join(log_dir, "launchd.log")}</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>{os.environ.get("PATH", "/usr/bin:/bin")}</string></dict>
  </dict>
</plist>
"""


def cron_line(project, top, minutes):
    spec = f"*/{minutes} * * * *" if minutes < 60 else f"0 */{max(1, minutes // 60)} * * *"
    cmd = " ".join(shlex.quote(a) for a in (FLEET, "schedule", "run-once", "--cwd", top))
    return f"{spec} {cmd} {CRON_TAG} {project}"


def plist_path(project):
    return os.path.expanduser(f"~/Library/LaunchAgents/{label(project)}.plist")


def install(cfg, top, project, home, minutes):
    if not unattended_cfg(cfg).get("command"):
        raise SystemExit("set fleet.unattended.command first (core/references/unattended.md)")
    p = paths(home, project)
    os.makedirs(p["dir"], exist_ok=True)
    if sys.platform == "darwin":
        dest = plist_path(project)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        subprocess.run(["launchctl", "unload", dest], capture_output=True)
        with open(dest, "w") as f:
            f.write(plist(project, top, minutes, p["dir"]))
        r = subprocess.run(["launchctl", "load", dest], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"launchctl load failed: {r.stderr.strip()}")
        print(f"installed {dest}: every {minutes} min")
    else:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        keep = [l for l in cur.splitlines() if not l.endswith(f"{CRON_TAG} {project}")]
        keep.append(cron_line(project, top, minutes))
        subprocess.run(["crontab", "-"], input="\n".join(keep) + "\n", text=True, check=True)
        print(f"installed a crontab line: every {minutes} min")
    print(f"allowed unattended: {', '.join(unattended_cfg(cfg)['allow']) or 'build and test only'} (never production)")
    return 0


def remove(project):
    if sys.platform == "darwin":
        dest = plist_path(project)
        if os.path.exists(dest):
            subprocess.run(["launchctl", "unload", dest], capture_output=True)
            os.remove(dest)
            print(f"removed {dest}")
        else:
            print("not installed")
    else:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        keep = [l for l in cur.splitlines() if not l.endswith(f"{CRON_TAG} {project}")]
        subprocess.run(["crontab", "-"], input="\n".join(keep) + ("\n" if keep else ""), text=True, check=True)
        print("removed the crontab line")
    return 0


def installed(project):
    if sys.platform == "darwin":
        return os.path.exists(plist_path(project))
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    return any(l.endswith(f"{CRON_TAG} {project}") for l in cur.splitlines())


def lock_held(path):
    try:
        with open(path) as f:
            pid = int(json.load(f).get("pid") or 0)
    except (OSError, ValueError):
        return False
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def attended_recently(path, grace_min, now=None):
    try:
        return (now or time.time()) - os.path.getmtime(path) < grace_min * 60
    except OSError:
        return False


def record(p, row):
    os.makedirs(p["dir"], exist_ok=True)
    with open(p["runs"], "a") as f:
        f.write(json.dumps(row) + "\n")


def alert(cfg, text):
    cmd = (cfg.get("fleet") or {}).get("alert_command")
    if cmd:
        subprocess.run(cmd, shell=True, env={**os.environ, "FLEET_ALERT": text}, timeout=60)


def run_once(cfg, top, project, home, runner=None, now=None):
    u = unattended_cfg(cfg)
    p = paths(home, project)
    os.makedirs(p["dir"], exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    skip = None
    if not u.get("command"):
        skip = "no fleet.unattended.command"
    elif os.path.exists(p["paused"]):
        skip = "paused"
    elif lock_held(p["lock"]):
        skip = "another unattended run is still going"
    elif attended_recently(p["heartbeat"], float(u["attended_grace_minutes"]), now):
        skip = "an attended PM session is running"
    if skip:
        record(p, {"ts": ts, "outcome": "skipped", "why": skip})
        print(f"skipped: {skip}")
        return 0
    log_path = os.path.join(p["dir"], f"run-{ts.replace(':', '')}.log")
    env = {**os.environ, "FLEET_UNATTENDED": "1", "FLEET_UNATTENDED_ALLOW": ",".join(u["allow"])}
    started = time.time()
    with open(log_path, "w") as log:
        proc = (runner or (lambda: subprocess.Popen(u["command"], shell=True, cwd=top, env=env, stdout=log,
                                                    stderr=subprocess.STDOUT, start_new_session=True)))()
        with open(p["lock"], "w") as f:
            json.dump({"pid": proc.pid, "started": ts}, f)
        try:
            code = proc.wait(timeout=float(u["max_hours"]) * 3600)
            outcome = "done" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                proc.terminate()
            code, outcome = None, "timed_out"
        finally:
            try:
                os.remove(p["lock"])
            except OSError:
                pass
    row = {"ts": ts, "outcome": outcome, "exit": code, "minutes": round((time.time() - started) / 60, 1), "log": log_path}
    record(p, row)
    if outcome != "done":
        alert(cfg, f"fleet unattended run {outcome} on {project} (log {log_path})")
    print(json.dumps(row))
    return 0 if outcome == "done" else 1


def status(cfg, project, home):
    p = paths(home, project)
    u = unattended_cfg(cfg)
    print(f"schedule: {'installed' if installed(project) else 'not installed'}"
          f"{', paused' if os.path.exists(p['paused']) else ''}{', a run is going' if lock_held(p['lock']) else ''}")
    print(f"allowed unattended: {', '.join(u['allow']) or 'build and test only'} (never production); "
          f"max {u['max_hours']} h a run")
    try:
        rows = [json.loads(l) for l in open(p["runs"])][-5:]
    except OSError:
        rows = []
    for r in rows:
        print(f"  {r['ts']} {r['outcome']}" + (f" ({r.get('why')})" if r.get("why") else f" {r.get('minutes')} min"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleet schedule", description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["install", "remove", "status", "pause", "resume", "run-once", "heartbeat", "selftest"])
    ap.add_argument("--every", default="2h")
    ap.add_argument("--cwd")
    a = ap.parse_args(argv)
    if a.action == "selftest":
        ok = [True]
        def check(name, got, want):
            ok[0] &= got == want
            print(f"{'ok  ' if got == want else 'FAIL'} {name}: {got!r}" + ("" if got == want else f" (want {want!r})"))
        selftest(check)
        return 0 if ok[0] else 1
    cfg, top, project, home = load(a.cwd)
    p = paths(home, project)
    if a.action == "install":
        return install(cfg, top, project, home, parse_every(a.every))
    if a.action == "remove":
        return remove(project)
    if a.action == "status":
        return status(cfg, project, home)
    if a.action in ("pause", "resume"):
        os.makedirs(p["dir"], exist_ok=True)
        if a.action == "pause":
            open(p["paused"], "w").close()
        elif os.path.exists(p["paused"]):
            os.remove(p["paused"])
        print(f"schedule {a.action}d for {project}")
        return 0
    if a.action == "heartbeat":
        if os.environ.get("FLEET_UNATTENDED") == "1":
            return 0  # an unattended run must not hold off the next one
        os.makedirs(os.path.dirname(p["heartbeat"]), exist_ok=True)
        open(p["heartbeat"], "a").close()
        os.utime(p["heartbeat"])
        return 0
    return run_once(cfg, top, project, home)


def selftest(check):
    import tempfile
    from types import SimpleNamespace
    check("schedule: 2h is 120 min", parse_every("2h"), 120)
    check("schedule: 45m is 45 min", parse_every("45m"), 45)
    try:
        parse_every("5m")
        check("schedule: under 15 min refused", False, True)
    except SystemExit:
        check("schedule: under 15 min refused", True, True)
    x = plist("acme/web", "/repo", 120, "/tmp/x")
    check("schedule: plist runs run-once in the repo every 2h",
          ("<integer>7200</integer>" in x, "run-once" in x, "<string>/repo</string>" in x, "dev.plane-fleet.unattended.acme-web" in x),
          (True, True, True, True))
    check("schedule: cron every 2h", cron_line("acme", "/repo", 120).startswith("0 */2 * * * "), True)
    check("schedule: cron every 30m", cron_line("acme", "/repo", 30).startswith("*/30 * * * * "), True)
    home = tempfile.mkdtemp(prefix="fleetschedule-")
    cfg = {"fleet": {"unattended": {"command": "true", "allow": ["merge"], "max_hours": 1}}}
    calls = []

    class Proc:
        pid = os.getpid()
        def __init__(self, code): self.code = code
        def wait(self, timeout=None): return self.code
    def runner(code):
        return lambda: (calls.append(code), Proc(code))[1]
    check("schedule: a clean run is done", run_once(cfg, "/repo", "p", home, runner(0)), 0)
    rows = [json.loads(l) for l in open(paths(home, "p")["runs"])]
    check("schedule: the run is recorded and the lock released", (rows[-1]["outcome"], os.path.exists(paths(home, "p")["lock"])), ("done", False))
    check("schedule: a failed run returns 1", run_once(cfg, "/repo", "p", home, runner(2)), 1)
    open(paths(home, "p")["paused"], "w").close()
    n = len(calls)
    run_once(cfg, "/repo", "p", home, runner(0))
    check("schedule: paused skips without starting", len(calls), n)
    os.remove(paths(home, "p")["paused"])
    hb = paths(home, "p")["heartbeat"]
    os.makedirs(os.path.dirname(hb), exist_ok=True)
    open(hb, "w").close()
    run_once(cfg, "/repo", "p", home, runner(0))
    check("schedule: an attended PM heartbeat skips the run", len(calls), n)
    os.utime(hb, (time.time() - 3600, time.time() - 3600))
    run_once(cfg, "/repo", "p", home, runner(0))
    check("schedule: an old heartbeat does not", len(calls), n + 1)
    with open(paths(home, "p")["lock"], "w") as f:
        json.dump({"pid": os.getpid()}, f)
    run_once(cfg, "/repo", "p", home, runner(0))
    check("schedule: a live lock skips the run", len(calls), n + 1)
    os.remove(paths(home, "p")["lock"])
    check("schedule: no command configured skips", run_once({}, "/repo", "q", home, runner(0)), 0)


if __name__ == "__main__":
    sys.exit(main())
