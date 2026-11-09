#!/usr/bin/env python3
"""fleetguard: keeps a fleet run alive while nobody is watching it.

  fleet guard start [--hours 24] [--probe-minutes 20] [--cwd DIR]
  fleet guard stop | status | check

A run dies quietly in two ways: the machine goes to sleep, or the login behind the agents
expires. The guard is one background process for the run. It holds off sleep, checks every few
minutes that a real agent call still works, and calls `fleet.alert_command` when two checks in a
row fail and again when it recovers. It writes what was lost to guard-events.jsonl, and
`fleet retro` reports it.

Without a `claude` command on the PATH the login check is off and sleep is still held off.
Standard library only. Python 3.9.
"""
import argparse, datetime, json, os, platform, shutil, signal, subprocess, sys, tempfile, time

TICK_S = 60
SLEEP_GAP_S = 180        # a tick this late means the machine was not running
FAILS_BEFORE_ALERT = 2


def state_home():
    return os.environ.get("PLANE_FLEET_HOME") or os.path.expanduser("~/.config/plane-fleet")


def path(name):
    return os.path.join(state_home(), name)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(kind, seconds):
    os.makedirs(state_home(), exist_ok=True)
    with open(path("guard-events.jsonl"), "a") as f:
        f.write(json.dumps({"ts": now_iso(), "kind": kind, "seconds": int(seconds)}) + "\n")


def read_state():
    try:
        with open(path("guard.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def keep_awake():
    """Holds off system sleep for as long as this process lives. Returns a child process or None."""
    system = platform.system()
    if system == "Darwin" and shutil.which("caffeinate"):
        return subprocess.Popen(["caffeinate", "-s", "-i", "-m", "-w", str(os.getpid())])
    if system == "Linux" and shutil.which("systemd-inhibit"):
        return subprocess.Popen(["systemd-inhibit", "--what=sleep:idle", "--who=plane-fleet",
                                 "--why=fleet run in progress", "sleep", "infinity"])
    if system == "Windows":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # continuous, system required
    return None


def probe():
    """True when one real agent call works, False when it does not, None when there is no CLI to try."""
    if not shutil.which("claude"):
        return None
    try:
        p = subprocess.run(["claude", "-p", "Reply with the word ok.", "--model", "haiku", "--max-turns", "1"],
                           cwd=tempfile.gettempdir(), capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (p.stdout + p.stderr).lower()
    return p.returncode == 0 and "/login" not in text and "not logged in" not in text


def alert_command(cwd):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import fleetctl
        return (fleetctl.project_config(cwd).get("fleet") or {}).get("alert_command")
    except Exception:
        return None


def alert(command, message):
    with open(path("guard.log"), "a") as f:
        f.write(f"{now_iso()} {message}\n")
    if command:
        try:
            subprocess.run(command, shell=True, env={**os.environ, "FLEET_ALERT": message}, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass
    system = platform.system()
    if system == "Darwin":
        text = message.replace('"', "'")
        subprocess.run(["osascript", "-e", f'display notification "{text}" with title "Fleet guard" sound name "Basso"'],
                       capture_output=True)
    elif system == "Linux" and shutil.which("notify-send"):
        subprocess.run(["notify-send", "Fleet guard", message], capture_output=True)


def loop(args):
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    awake = keep_awake()
    command = alert_command(args.cwd)
    deadline = time.time() + args.hours * 3600
    next_probe = time.time()
    fails, down_since = 0, None
    last = time.time()
    while not stop["now"] and time.time() < deadline:
        time.sleep(TICK_S)
        t = time.time()
        if t - last > SLEEP_GAP_S:
            record("asleep", t - last - TICK_S)
        last = t
        if t < next_probe:
            continue
        next_probe = t + args.probe_minutes * 60
        ok = probe()
        if ok is None:
            continue
        if ok:
            fails = 0
            if down_since:
                record("agent_down", t - down_since)
                alert(command, "The fleet's agent login works again. Restart anything that stopped.")
                down_since = None
            continue
        fails += 1
        if fails >= FAILS_BEFORE_ALERT and not down_since:
            down_since = t
            alert(command, "The fleet's agents cannot run. The login probably expired. Run /login in the PM session.")
    if down_since:
        record("agent_down", time.time() - down_since)
    if awake:
        awake.terminate()
    try:
        os.remove(path("guard.json"))
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(prog="fleet guard")
    parser.add_argument("action", choices=["start", "stop", "status", "check", "_run"])
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--probe-minutes", type=float, default=20)
    parser.add_argument("--cwd", default=os.getcwd())
    args = parser.parse_args()
    state = read_state()
    running = state if alive(state.get("pid")) else None

    if args.action == "_run":
        loop(args)
    elif args.action == "start":
        if running:
            print(f"guard already running, pid {running['pid']}, until {running['until']}")
            return 0
        os.makedirs(state_home(), exist_ok=True)
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_run", "--hours", str(args.hours),
                              "--probe-minutes", str(args.probe_minutes), "--cwd", args.cwd],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        until = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=args.hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path("guard.json"), "w") as f:
            json.dump({"pid": p.pid, "until": until, "cwd": args.cwd}, f)
        print(f"guard started, pid {p.pid}, until {until}")
    elif args.action == "stop":
        if running:
            os.kill(int(running["pid"]), signal.SIGTERM)
            print("guard stopping")
        else:
            print("guard not running")
    elif args.action == "status":
        print(f"guard running, pid {running['pid']}, until {running['until']}" if running else "guard not running")
    elif args.action == "check":
        ok = probe()
        print({True: "agent login works", False: "agent login FAILED", None: "no claude command, login check is off"}[ok])
        return 1 if ok is False else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
