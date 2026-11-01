#!/usr/bin/env python3
"""fleetwatch: one background watcher per thing a session waits on.

2026-10-31, one engineer waiting on a slow pre-push hook: every time it checked back it
started a new `until grep -q ^exit push.log; do sleep 10; done` instead of reusing the one
already running. 22 copies of that wait and 6 copies of a `gh run view` poller were alive at
once under one PM session, 50 background shells in all, and the CI poller copies made about
one GitHub API call a second.

So every wait goes through a name. A second start under a name that is still running does
not start anything: it says who holds the name and where its output is, and exits 75.

  fleet watch <name> --until '<shell test>' [--every S] [--timeout S] [-- <command run after>]
  fleet watch <name> -- <command>          run a long command (a push, a build) under the name
  fleet watch --show <name>                status and the last lines of its output
  fleet watch --list                       every watcher, live or finished in the last day
  fleet watch --stop <name>                stop it and what it started
  fleet watch --stop-prefix <prefix>       stop every live watcher whose name starts with it
                                           (a ticket id: run it before you report)

Run the start form with run_in_background; it prints the output as it goes and exits with the
command's exit code (124 on timeout). Name it after the ticket and the thing:
`PROJ-12-ci`, `PROJ-12-push`. Names are shared across sessions on this machine, so two
sessions waiting on the same CI run share one watcher too.

Exit codes: the command's own, 124 timed out, 75 already watched (nothing started),
2 usage error. Standard library only. Python 3.9.
"""
import json, os, re, signal, subprocess, sys, time

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def home():
    return os.path.join(os.environ.get("PLANE_FLEET_HOME") or os.path.expanduser("~/.config/plane-fleet"), "watches")


def paths(name):
    d = home()
    return os.path.join(d, name + ".json"), os.path.join(d, name + ".log")


def read(name):
    try:
        return json.load(open(paths(name)[0]))
    except (OSError, ValueError):
        return None


def write(name, rec):
    os.makedirs(home(), exist_ok=True)
    tmp = paths(name)[0] + ".tmp"
    json.dump(rec, open(tmp, "w"))
    os.replace(tmp, paths(name)[0])


def alive(rec):
    """Is the process that holds this record still the watcher it says it is?"""
    if not rec or rec.get("ended_at") is not None:
        return False
    pid = rec.get("pid")
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    try:
        cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return "fleetwatch" in cmd and rec["name"] in cmd


def ago(t):
    s = int(time.time() - t)
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def tail(path, n=8):
    try:
        return open(path, errors="replace").read().splitlines()[-n:]
    except OSError:
        return []


def claim(name):
    """Take the name atomically. Returns the holder's record when someone live already has it."""
    os.makedirs(home(), exist_ok=True)
    lock = paths(name)[0] + ".lock"
    for _ in range(50):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > 10:   # a crashed claim
                    os.unlink(lock)
                    continue
            except OSError:
                pass
            time.sleep(0.1)
    try:
        rec = read(name)
        if alive(rec):
            return rec
        write(name, {"name": name, "pid": os.getpid(), "started_at": time.time(), "ended_at": None,
                     "cwd": os.getcwd(), "what": None, "exit": None})
        return None
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass


def start(name, until, every, timeout, cmd):
    holder = claim(name)
    if holder:
        print(f"already watching '{name}': pid {holder['pid']}, up {ago(holder['started_at'])}, "
              f"waiting on: {holder.get('what') or '?'}\noutput: {paths(name)[1]}\n"
              f"Not starting a second one. Read it with `fleet watch --show {name}`; you are notified "
              f"when the first one exits.")
        return 75
    what = (f"until {until}" if until else "") + (" then " if until and cmd else "") + (" ".join(cmd) if cmd else "")
    rec = read(name); rec["what"] = what; write(name, rec)
    log = open(paths(name)[1], "w", buffering=1)
    child = {"p": None}

    def stop(*_):
        if child["p"] and child["p"].poll() is None:
            try:
                os.killpg(child["p"].pid, signal.SIGTERM)
            except OSError:
                pass
        finish(name, 143, "stopped")
        sys.exit(143)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def say(line):
        print(line, flush=True); log.write(line + "\n")

    deadline = time.time() + timeout if timeout else None
    if until:
        while subprocess.run(["bash", "-c", until], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            if deadline and time.time() >= deadline:
                say(f"timed out after {ago(rec['started_at'])} waiting for: {until}")
                finish(name, 124)
                return 124
            time.sleep(every)
        say(f"done waiting ({ago(rec['started_at'])}): {until}")
    code = 0
    if cmd:
        p = child["p"] = subprocess.Popen(["bash", "-c", " ".join(cmd)] if len(cmd) == 1 else cmd,
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                          errors="replace", start_new_session=True)
        for line in p.stdout:
            say(line.rstrip("\n"))
            if deadline and time.time() >= deadline:
                break
        try:
            code = p.wait(timeout=max(1, deadline - time.time()) if deadline else None)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGTERM)
            say(f"timed out after {ago(rec['started_at'])}: {' '.join(cmd)}")
            code = 124
    finish(name, code)
    return code


def finish(name, code, how="exited"):
    rec = read(name) or {"name": name}
    if rec.get("pid") == os.getpid():
        rec.update(ended_at=time.time(), exit=code, how=how)
        write(name, rec)


def show(name):
    rec = read(name)
    if not rec:
        print(f"no watcher named '{name}'")
        return 1
    state = "running" if alive(rec) else (f"{rec.get('how', 'exited')} {rec.get('exit')}" if rec.get("ended_at") else "dead (no exit recorded)")
    print(f"{name}: {state} · pid {rec['pid']} · started {ago(rec['started_at'])} ago · {rec.get('what') or ''}")
    for l in tail(paths(name)[1]):
        print("  " + l)
    return 0


def listing():
    d = home()
    rows = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".json"):
            rec = read(f[:-5])
            if not rec:
                continue
            live = alive(rec)
            if not live and rec.get("ended_at") and time.time() - rec["ended_at"] > 86400:
                continue
            rows.append((rec, live))
    if not rows:
        print("watchers: none")
    for rec, live in rows:
        st = "running" if live else (f"exit {rec.get('exit')}" if rec.get("ended_at") else "dead")
        print(f"  {rec['name']:<28} {st:<9} up {ago(rec['started_at']):>7}  {(rec.get('what') or '')[:80]}")
    return 0


def stop_named(name):
    rec = read(name)
    if not alive(rec):
        print(f"'{name}' is not running")
        return 1
    os.kill(rec["pid"], signal.SIGTERM)
    print(f"stopped '{name}' (pid {rec['pid']})")
    return 0


def stop_prefix(prefix):
    """Stop every live watcher whose name starts with prefix. 0 when none is left running."""
    d = home()
    stopped, left = [], []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith(".json") or not f.startswith(prefix):
            continue
        rec = read(f[:-5])
        if not alive(rec):
            continue
        try:
            os.kill(rec["pid"], signal.SIGTERM)
            stopped.append(rec)
        except OSError:
            left.append(rec)
    deadline = time.time() + 5
    while time.time() < deadline and any(alive(read(r["name"])) for r in stopped):
        time.sleep(0.2)
    left += [r for r in stopped if alive(read(r["name"]))]
    for r in stopped:
        if r not in left:
            print(f"stopped '{r['name']}' (pid {r['pid']})")
    for r in left:
        print(f"still running '{r['name']}' (pid {r['pid']})")
    if not stopped and not left:
        print(f"no live watcher starts with '{prefix}'")
    return 1 if left else 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n", 2)[2].split("Exit codes")[0].rstrip())
        return 0 if argv else 2
    if argv[0] == "--list":
        return listing()
    if argv[0] == "--stop-prefix":
        if len(argv) < 2 or not argv[1].strip():
            print("need a prefix", file=sys.stderr); return 2
        return stop_prefix(argv[1])
    if argv[0] in ("--show", "--stop", "--selftest"):
        if argv[0] == "--selftest":
            return selftest()
        if len(argv) < 2:
            print("need a name", file=sys.stderr); return 2
        return show(argv[1]) if argv[0] == "--show" else stop_named(argv[1])
    name, rest = argv[0], argv[1:]
    if not NAME_RE.match(name):
        print(f"bad name '{name}': letters, digits, dot, dash, underscore", file=sys.stderr)
        return 2
    until, every, timeout, cmd = None, 10.0, None, []
    while rest:
        a = rest.pop(0)
        if a == "--":
            cmd = rest; break
        if a in ("--until", "--every", "--timeout") and rest:
            v = rest.pop(0)
            if a == "--until": until = v
            elif a == "--every": every = max(2.0, float(v))
            else: timeout = float(v)
        else:
            print(f"unknown arg: {a}", file=sys.stderr); return 2
    if not until and not cmd:
        print("give --until '<test>' or -- <command>", file=sys.stderr); return 2
    return start(name, until, every, timeout, cmd)


def selftest():
    import tempfile
    fails = []

    def check(n, got, want):
        ok = got == want
        print(("ok   " if ok else "FAIL ") + n + ("" if ok else f": got {got!r}, want {want!r}"))
        if not ok:
            fails.append(n)
    os.environ["PLANE_FLEET_HOME"] = tempfile.mkdtemp()
    me = [sys.executable, os.path.abspath(__file__)]
    first = subprocess.Popen(me + ["t-1", "--until", "test -f " + os.path.join(home(), "go"), "--every", "2"],
                             stdout=subprocess.PIPE, text=True)
    time.sleep(1.0)
    dup = subprocess.run(me + ["t-1", "--until", "true"], capture_output=True, text=True)
    check("watch: a second start under a live name starts nothing", dup.returncode, 75)
    check("watch: it names the holder", "already watching 't-1'" in dup.stdout, True)
    other = subprocess.run(me + ["t-2", "--", "echo hi"], capture_output=True, text=True)
    check("watch: another name runs", (other.returncode, other.stdout.strip()), (0, "hi"))
    open(os.path.join(home(), "go"), "w").close()
    out, _ = first.communicate(timeout=10)
    check("watch: the first one finishes when its test passes", first.returncode, 0)
    again = subprocess.run(me + ["t-1", "--", "exit 3"], capture_output=True, text=True)
    check("watch: a finished name can be reused", again.returncode, 3)
    check("watch: the record keeps the exit", read("t-1")["exit"], 3)
    to = subprocess.run(me + ["t-3", "--until", "false", "--every", "2", "--timeout", "1"], capture_output=True, text=True)
    check("watch: a timeout exits 124", to.returncode, 124)
    check("watch: bad names are refused", subprocess.run(me + ["../x", "--", "true"], capture_output=True).returncode, 2)
    w = [subprocess.Popen(me + [n, "--until", "false", "--every", "2"], stdout=subprocess.DEVNULL)
         for n in ("T-9-ci", "T-9-push", "T-90-ci")]
    time.sleep(1.0)
    sp = subprocess.run(me + ["--stop-prefix", "T-9-"], capture_output=True, text=True)
    check("watch: --stop-prefix exits 0", sp.returncode, 0)
    check("watch: --stop-prefix stops each match", sorted(l.split("'")[1] for l in sp.stdout.splitlines() if l.startswith("stopped")),
          ["T-9-ci", "T-9-push"])
    check("watch: --stop-prefix leaves other names running", alive(read("T-90-ci")), True)
    check("watch: --stop-prefix with nothing live", subprocess.run(me + ["--stop-prefix", "T-9-"], capture_output=True).returncode, 0)
    check("watch: --stop-prefix needs a prefix", subprocess.run(me + ["--stop-prefix"], capture_output=True).returncode, 2)
    subprocess.run(me + ["--stop", "T-90-ci"], capture_output=True)
    for p in w:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
