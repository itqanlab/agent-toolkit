#!/usr/bin/env python3
"""fleetres — the machine's resource gate, on macOS, Linux and Windows.

2026-10-29, a 12-core, 32 GB Mac running only a terminal, Docker and four fleet sessions:
load 72, 24.7 of 25.6 GB swap used, 900 MB of swap left. The biggest process was not a
fleet session. watchman, the file watcher Jest uses, held 11 GB: its watch on the repo root
covered every worktree's node_modules, and the lanes changed files so fast that FSEvents
dropped events and watchman re-crawled the whole tree 5,863 times. The old gate read one
macOS number, let the PM decide, and never named the process that was eating the machine.

So this module measures the machine the same way on every OS, judges it against limits
scaled to that machine (cores, RAM, disk), names the biggest processes and what is safe to
do about each, and is enforced in code: `run-lane` defers a lane and the usage-pacer hook
holds a heavy Claude spawn while the gate is closed.

  fleet resources [--cwd DIR] [--json] [--top N]
  fleet resources --wait [--max-wait SEC]    block until the gate opens (lanes run this
                                             before Jest, Playwright or a server)

Levels and exit codes: 0 ok · 1 tight (spawn light work only) · 2 closed (spawn nothing)
· 3 critical (spawn nothing, and free memory now: see `fixes`).

Limits come from fleet.resources in the merged project config; every key is optional:
  {"mem_avail_pct": [25, 15, 8],        tight, closed, critical: memory the OS can hand out
   "swap_of_ram_pct": [25, 40, 60],     swap in use, as a share of RAM (macOS grows swap
                                        files on demand, so "% of swap" reads high when
                                        healthy; swap against RAM does not)
   "commit_pct": [80, 88, 95],          Windows: committed memory against the commit limit
   "load_per_core": [1.5, 2.0, 4.0],    1-minute load per core (Linux, macOS)
   "cpu_busy_pct": [85, 92, 98],        Windows: CPU busy over one second
   "disk_free_gb": [15, 6, 2],          free space where the repo and temp dirs live
   "per_heavy_gb": 3,                   one engineer or tester running a server, Jest or
                                        Playwright (measured 2.5 to 5 GB on 2026-10-29)
   "reserve_gb": null,                  kept back for the owner; default max(4, 15% of RAM)
   "max_heavy": 4,                      never more heavy sessions than this
   "hog_gb": null}                      a process this big is named; default max(1.5, 5% RAM)

Standard library only. Python 3.9.
"""
import json, os, platform, re, shutil, subprocess, sys, tempfile, time

LEVELS = ["ok", "tight", "closed", "critical"]
DEFAULTS = {"mem_avail_pct": [25, 15, 8], "swap_of_ram_pct": [25, 40, 60], "commit_pct": [80, 88, 95],
            "load_per_core": [1.5, 2.0, 4.0], "cpu_busy_pct": [85, 92, 98], "disk_free_gb": [15, 6, 2],
            "per_heavy_gb": 3, "reserve_gb": None, "max_heavy": 4, "hog_gb": None}
GB = 1024 ** 3

# What a big process usually is, and what is safe to do about it. "safe" fixes free memory
# without losing anyone's work; the PM may run them. The rest are the owner's call.
KNOWN = [
    (r"\bwatchman\b", "file watcher (Jest, Metro, Buck). A watch rooted at the repo covers every worktree "
     "inside it, with its node_modules", "watchman shutdown-server", True,
     "turn watchman off for Jest (watchman: false) or keep worktrees outside the repo; never ignore_dirs the worktrees"),
    (r"nx/src/daemon|nx[/\\]bin[/\\]daemon", "Nx daemon", "nx daemon --stop (or kill it)", True,
     "run fleet sessions with NX_DAEMON=false"),
    (r"chrome-headless-shell|headless_shell|--headless", "headless browser (Playwright, Puppeteer)",
     "kill it if no live session owns it (fleet-sweep finds the owner)", True, "close the browser in a finally"),
    (r"jest-worker|jest\.js|vitest", "test workers", "they end with their run; a leftover can be killed", True,
     "Jest --maxWorkers=2"),
    (r"tsserver|typescript/lib/tsserver|eslint_d|vscode-eslint", "editor language server",
     "restart it from the editor", False, None),
    (r"com\.apple\.Virtualization|vmmem|VmmemWSL|qemu-system|com\.docker|Docker Desktop|colima|OrbStack",
     "container or VM", "lower its memory limit in Docker or VM settings", False, None),
    (r"WebKit\.WebContent|Google Chrome Helper|chrome\.exe|firefox|msedge|Safari", "browser tabs",
     "close tabs the owner does not need", False, None),
    (r"\bfseventsd\b", "macOS file-event service (busy means something churns files under a watched tree)",
     "find the watcher (often watchman) and stop it", False, None),
    (r"\bmds(_stores|worker)?\b|SearchIndexer|tracker-miner", "search indexer crawling build output",
     "exclude the worktree and node_modules dirs from indexing", False, None),
    (r"legacyScreenSaver", "screen saver (leaks over days)", "kill it; the OS restarts it", True, None),
]


def run(args, timeout=10):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- probes (one per OS)
def _size(s):
    """'11G' / '4107M' / '512K' / '123,456 K' -> bytes."""
    m = re.match(r"([\d.]+)([KMGT]?)", s.replace(",", "").replace(" ", ""))
    if not m:
        return 0
    return int(float(m.group(1)) * {"": 1, "K": 1024, "M": 1024 ** 2, "G": GB, "T": 1024 ** 4}[m.group(2)])


def probe_mac(top_n):
    s = {"os": "macos", "cores": os.cpu_count() or 1, "load1": os.getloadavg()[0]}
    s["ram"] = int(run(["sysctl", "-n", "hw.memsize"]) or 0)
    lvl = run(["sysctl", "-n", "kern.memorystatus_level"]).strip()
    s["mem_avail"] = int(s["ram"] * int(lvl) / 100) if lvl.isdigit() else None
    sw = run(["sysctl", "-n", "vm.swapusage"])
    m = re.search(r"total = ([\d.]+)M\s+used = ([\d.]+)M", sw)
    s["swap_total"], s["swap_used"] = (int(float(m.group(1)) * 1024 ** 2), int(float(m.group(2)) * 1024 ** 2)) if m else (0, 0)
    procs = []
    if top_n:
        # top's MEM is the footprint, compressed pages included; ps RSS misses what macOS compressed
        out = run(["top", "-l", "1", "-o", "mem", "-n", str(max(top_n, 15)), "-stats", "pid,mem,cpu,command"], timeout=15)
        rows = out.split("\n")
        start = next((i for i, l in enumerate(rows) if l.lstrip().startswith("PID")), len(rows))
        for l in rows[start + 1:]:
            p = l.split(None, 3)
            if len(p) == 4 and p[0].isdigit():
                procs.append({"pid": int(p[0]), "mem": _size(p[1].rstrip("+-")), "cpu": float(p[2] or 0), "name": p[3].strip()})
    s["procs"] = _with_cmdlines(procs)
    return s


def probe_linux(top_n):
    s = {"os": "linux", "cores": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1),
         "load1": os.getloadavg()[0]}
    mi = {}
    try:
        for l in open("/proc/meminfo"):
            k, v = l.split(":", 1)
            mi[k] = int(v.split()[0]) * 1024
    except OSError:
        pass
    s["ram"], s["mem_avail"] = mi.get("MemTotal", 0), mi.get("MemAvailable")
    s["swap_total"], s["swap_used"] = mi.get("SwapTotal", 0), mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)
    try:   # a container or cgroup limit is the real ceiling
        lim = open("/sys/fs/cgroup/memory.max").read().strip()
        cur = int(open("/sys/fs/cgroup/memory.current").read().strip())
        if lim.isdigit() and int(lim) < s["ram"]:
            s["ram"], s["mem_avail"] = int(lim), max(0, int(lim) - cur)
    except (OSError, ValueError):
        pass
    procs = []
    if top_n:
        for l in run(["ps", "-eo", "pid=,rss=,pcpu=,args=", "--sort=-rss"]).splitlines()[:max(top_n, 15)]:
            p = l.split(None, 3)
            if len(p) == 4:
                procs.append({"pid": int(p[0]), "mem": int(p[1]) * 1024, "cpu": float(p[2]), "name": os.path.basename(p[3].split()[0]), "cmd": p[3][:300]})
    s["procs"] = procs
    return s


def probe_windows(top_n):
    import ctypes
    from ctypes import wintypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + \
                   [(n, ctypes.c_ulonglong) for n in ("tp", "ap", "tpf", "apf", "tv", "av", "aev")]
    ms = MS(); ms.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
    s = {"os": "windows", "cores": os.cpu_count() or 1, "ram": ms.tp, "mem_avail": ms.ap,
         "commit_limit": ms.tpf, "commit_used": ms.tpf - ms.apf, "swap_total": 0, "swap_used": 0}

    def times():
        i, k, u = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
        f = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
        return f(i), f(k) + f(u)   # kernel time includes idle
    i0, t0 = times(); time.sleep(1); i1, t1 = times()
    s["cpu_busy"] = 100.0 * (1 - (i1 - i0) / max(1, t1 - t0))
    procs = []
    if top_n:
        import csv, io
        for r in csv.reader(io.StringIO(run(["tasklist", "/fo", "csv", "/nh"]))):
            if len(r) >= 5:
                procs.append({"pid": int(r[1]), "mem": _size(r[4].replace(" K", "K")), "cpu": 0.0, "name": r[0]})
        procs = sorted(procs, key=lambda p: -p["mem"])[:max(top_n, 15)]
    s["procs"] = procs
    return s


def _with_cmdlines(procs):
    """macOS top truncates names; add the full command line so a node process says whose it is."""
    if not procs:
        return procs
    out = run(["ps", "-o", "pid=,args=", "-p", ",".join(str(p["pid"]) for p in procs)])
    cmd = {int(l.split(None, 1)[0]): l.split(None, 1)[1][:300] for l in out.splitlines() if len(l.split(None, 1)) == 2}
    for p in procs:
        p["cmd"] = cmd.get(p["pid"], p["name"])
    return procs


def probe(paths=(), top_n=8):
    sysname = platform.system()
    s = (probe_mac if sysname == "Darwin" else probe_windows if sysname == "Windows" else probe_linux)(top_n)
    disks, seen = [], set()
    for p in [*paths, tempfile.gettempdir()]:
        try:
            u = shutil.disk_usage(p)
        except OSError:
            continue
        key = (u.total, u.free // GB)
        if key not in seen:
            seen.add(key); disks.append({"path": p, "free": u.free, "total": u.total})
    s["disks"] = disks
    s["watch_roots"] = watchman_roots() if any(re.search(r"\bwatchman\b", p.get("cmd", p["name"])) for p in s["procs"]) or shutil.which("watchman") else []
    return s


def watchman_roots():
    """Roots watchman holds, without starting it (a dead server stays dead)."""
    if not shutil.which("watchman"):
        return []
    try:
        r = subprocess.run(["watchman", "--no-spawn", "watch-list"], capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout).get("roots", []) if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


# ---------------------------------------------------------------- judgement (pure, tested)
def limits(cfg):
    out = dict(DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("resources") or {}).items() if k in DEFAULTS and v is not None})
    return out


def _grade(value, steps, higher_is_worse=True):
    """steps = [tight, closed, critical]; returns 0..3."""
    lvl = 0
    for i, t in enumerate(steps, start=1):
        if (value >= t) if higher_is_worse else (value <= t):
            lvl = i
    return lvl


def judge(s, cfg=None, worktree_dirs=()):
    L = limits(cfg)
    ram = s.get("ram") or 1
    reasons, lvl = [], 0

    def hit(level, text):
        nonlocal lvl
        if level:
            lvl = max(lvl, level); reasons.append(f"{LEVELS[level]}: {text}")

    if s.get("mem_avail") is not None:
        pct = 100.0 * s["mem_avail"] / ram
        hit(_grade(pct, L["mem_avail_pct"], higher_is_worse=False), f"memory available {pct:.0f}% ({s['mem_avail'] / GB:.1f} of {ram / GB:.0f} GB)")
    if s.get("swap_used"):
        pct = 100.0 * s["swap_used"] / ram
        hit(_grade(pct, L["swap_of_ram_pct"]), f"swap in use {s['swap_used'] / GB:.1f} GB ({pct:.0f}% of RAM)")
        if s.get("swap_total") and s["swap_total"] - s["swap_used"] < GB and pct >= L["swap_of_ram_pct"][0]:
            hit(3, f"swap nearly full ({(s['swap_total'] - s['swap_used']) / GB:.1f} GB left)")
    if s.get("commit_limit"):
        pct = 100.0 * s["commit_used"] / s["commit_limit"]
        hit(_grade(pct, L["commit_pct"]), f"committed memory {pct:.0f}% of the limit")
    if s.get("load1") is not None:
        per = s["load1"] / max(1, s["cores"])
        hit(_grade(per, L["load_per_core"]), f"load {s['load1']:.0f} on {s['cores']} cores ({per:.1f} per core)")
    if s.get("cpu_busy") is not None:
        hit(_grade(s["cpu_busy"], L["cpu_busy_pct"]), f"CPU {s['cpu_busy']:.0f}% busy")
    for d in s.get("disks") or []:
        hit(_grade(d["free"] / GB, L["disk_free_gb"], higher_is_worse=False), f"disk {d['free'] / GB:.0f} GB free at {d['path']}")

    reserve = L["reserve_gb"] if L["reserve_gb"] is not None else max(4, 0.15 * ram / GB)
    avail_gb = (s["mem_avail"] / GB) if s.get("mem_avail") is not None else 0
    room = int(max(0, avail_gb - reserve) // max(0.5, L["per_heavy_gb"]))
    room = min(room, L["max_heavy"], max(1, s["cores"] // 3))
    if lvl >= 2:
        room = 0

    hog_b = (L["hog_gb"] if L["hog_gb"] is not None else max(1.5, 0.05 * ram / GB)) * GB
    hogs = []
    for p in s.get("procs") or []:
        text = p.get("cmd") or p["name"]
        if p["mem"] < hog_b and p.get("cpu", 0) < 100:
            continue
        h = {"pid": p["pid"], "name": p["name"][:40], "mem_gb": round(p["mem"] / GB, 1), "cpu": p.get("cpu", 0),
             "fleet": any(w and w in text for w in worktree_dirs)}
        for pat, what, fix, safe, prevent in KNOWN:
            if re.search(pat, text) or re.search(pat, p["name"]):
                h.update(what=what, fix=fix, safe=safe, prevent=prevent)
                break
        hogs.append(h)

    warnings = []
    for root in s.get("watch_roots") or []:
        inside = [w for w in worktree_dirs if w and (w + os.sep).startswith(root.rstrip(os.sep) + os.sep)]
        if inside:
            # Never "fix" this with ignore_dirs in an untracked root .watchmanconfig: watchman then
            # roots every worktree at the repo, the worktrees are ignored, and Jest finds no tests,
            # so a pre-push hook passes green with failing tests (2026-10-29).
            warnings.append(f"watchman watches {root}, which holds the worktrees ({inside[0]}): every lane's file churn "
                            f"lands on it. `watchman watch-del {root}` now; to stop it coming back, turn watchman off "
                            f"for Jest (watchman: false in the Jest config) or keep worktrees outside the repo.")
    return {"level": LEVELS[lvl], "code": lvl, "reasons": reasons, "room_heavy": room, "hogs": hogs, "warnings": warnings}


def admit(j, heavy):
    """May a new session start? Heavy (an engineer or tester that runs a server, Jest or a
    browser): the gate must be ok or tight and leave room for one more. Light (a scan, a
    plan, a review in a worktree with no server): anything short of critical."""
    if heavy:
        return j["code"] <= 1 and j["room_heavy"] >= 1
    return j["code"] <= 2


# ---------------------------------------------------------------- cli
def summary_line(s, j):
    parts = [j["level"].upper()]
    if s.get("mem_avail") is not None:
        parts.append(f"mem {100 * s['mem_avail'] / (s['ram'] or 1):.0f}% free of {s['ram'] / GB:.0f} GB")
    if s.get("swap_used"):
        parts.append(f"swap {s['swap_used'] / GB:.1f} GB")
    if s.get("load1") is not None:
        parts.append(f"load {s['load1']:.0f}/{s['cores']} cores")
    if s.get("cpu_busy") is not None:
        parts.append(f"cpu {s['cpu_busy']:.0f}%")
    if s.get("disks"):
        parts.append(f"disk {min(d['free'] for d in s['disks']) / GB:.0f} GB free")
    parts.append(f"room for {j['room_heavy']} heavy")
    top = [h for h in j["hogs"] if not h["fleet"]][:2]
    if top:
        parts.append("hogs " + ", ".join(f"{h['name']} {h['mem_gb']} GB" for h in top))
    return " · ".join(parts)


def context(cwd):
    """Repo paths and config for a cwd; works outside a fleet repo too."""
    cfg, paths, wdirs = {}, [], []
    try:
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import fleetctl
        cfg = (fleetctl.project_config(cwd) or {}).get("fleet") or {}
        common = fleetctl.git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
        repo = os.path.dirname(common.rstrip("/")) if common else cwd
        paths.append(repo)
        out = fleetctl.git(repo, "worktree", "list", "--porcelain") or ""
        trees = [l[9:] for l in out.splitlines() if l.startswith("worktree ")][1:]
        wdirs = sorted({os.path.dirname(t) for t in trees}) or [os.path.join(repo, ".claude", "worktrees")]
    except Exception:
        paths.append(cwd)
    return cfg, paths, wdirs


def render(s, j):
    out = [f"machine: {summary_line(s, j)}"]
    out += [f"  {r}" for r in j["reasons"]]
    for h in j["hogs"]:
        tag = "fleet" if h["fleet"] else "machine"
        line = f"  hog [{tag}] pid {h['pid']} {h['name']} {h['mem_gb']} GB" + (f" cpu {h['cpu']:.0f}%" if h["cpu"] >= 100 else "")
        if h.get("what"):
            line += f" · {h['what']} · fix: {h['fix']}" + (" (safe)" if h["safe"] else " (owner's call)")
        out.append(line)
    out += [f"  warning: {w}" for w in j["warnings"]]
    return "\n".join(out)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="fleet resources")
    ap.add_argument("--cwd"); ap.add_argument("--json", action="store_true"); ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--wait", action="store_true"); ap.add_argument("--max-wait", type=int, default=240)
    ap.add_argument("--gate", choices=["heavy", "light"], help="exit 0 when a new session of this weight may start, 2 when not")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    cfg, paths, wdirs = context(a.cwd or os.getcwd())
    if a.wait:
        # light samples (no process list) until the gate opens or the wait runs out; at most
        # 240 s by default so a Claude session's prompt cache survives the call
        end = time.time() + a.max_wait
        while True:
            s = probe(paths, top_n=0); j = judge(s, cfg, wdirs)
            if j["code"] <= 1 or time.time() >= end:
                break
            time.sleep(min(20, max(1, end - time.time())))
        print(f"machine: {summary_line(s, j)}" + ("" if j["code"] <= 1 else " · still closed, wait again or report"))
        return j["code"]
    s = probe(paths, top_n=a.top); j = judge(s, cfg, wdirs)
    if a.gate:
        ok = admit(j, a.gate == "heavy")
        if a.json:
            print(json.dumps({"admit": ok, "level": j["level"], "room_heavy": j["room_heavy"], "summary": summary_line(s, j),
                              "reasons": j["reasons"], "hogs": j["hogs"], "warnings": j["warnings"]}))
        else:
            print(("admit" if ok else "hold") + f" {a.gate}: {summary_line(s, j)}")
        return 0 if ok else 2
    if a.json:
        print(json.dumps({**j, "summary": summary_line(s, j), "sample": {k: v for k, v in s.items() if k != "procs"}}, indent=2))
    else:
        print(render(s, j))
    return j["code"]


def selftest(check=None):
    fails = []
    if check is None:
        def check(name, got, want):
            ok = got == want
            print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": got {got!r}, want {want!r}"))
            if not ok:
                fails.append(name)
    mac_bad = {"os": "macos", "cores": 12, "load1": 71.9, "ram": 32 * GB, "mem_avail": int(0.22 * 32 * GB),
               "swap_total": int(25.6 * GB), "swap_used": int(24.7 * GB), "disks": [{"path": "/", "free": 120 * GB, "total": 500 * GB}],
               "procs": [{"pid": 838, "name": "watchman", "mem": 11 * GB, "cpu": 0.0, "cmd": "/opt/homebrew/bin/watchman --foreground"},
                         {"pid": 9, "name": "node", "mem": 2 * GB, "cpu": 30.0, "cmd": "node /r/.claude/worktrees/T-1/node_modules/nx"}],
               "watch_roots": ["/r"]}
    j = judge(mac_bad, {}, ["/r/.claude/worktrees"])
    check("res: 2026-10-29 Mac is critical", j["level"], "critical")
    check("res: critical leaves no room", j["room_heavy"], 0)
    check("res: watchman named as a safe machine hog", (j["hogs"][0]["name"], j["hogs"][0]["fleet"], j["hogs"][0]["safe"]), ("watchman", False, True))
    check("res: a worktree process is the fleet's", j["hogs"][1]["fleet"], True)
    check("res: watch over the worktrees warned", len(j["warnings"]), 1)
    mac_ok = dict(mac_bad, load1=6.0, mem_avail=int(0.55 * 32 * GB), swap_used=2 * GB, swap_total=3 * GB, procs=[], watch_roots=[])
    j = judge(mac_ok, {})
    check("res: stale swap on a calm Mac is ok", j["level"], "ok")
    check("res: room scales with free memory", j["room_heavy"], 4)
    check("res: load at 2x cores closes", judge(dict(mac_ok, load1=25.0), {})["level"], "closed")
    check("res: config overrides a limit", judge(dict(mac_ok, load1=25.0), {"resources": {"load_per_core": [3, 4, 6]}})["level"], "ok")
    lin = {"os": "linux", "cores": 4, "load1": 1.0, "ram": 8 * GB, "mem_avail": int(0.10 * 8 * GB), "swap_total": 2 * GB,
           "swap_used": 0, "disks": [{"path": "/", "free": 50 * GB, "total": 100 * GB}], "procs": []}
    check("res: Linux at 10% available is closed", judge(lin, {})["level"], "closed")
    win = {"os": "windows", "cores": 8, "ram": 16 * GB, "mem_avail": 8 * GB, "commit_limit": 24 * GB, "commit_used": int(23 * GB),
           "cpu_busy": 40.0, "swap_total": 0, "swap_used": 0, "disks": [{"path": "C:\\", "free": 1 * GB, "total": 200 * GB}], "procs": []}
    check("res: Windows full commit and disk is critical", judge(win, {})["level"], "critical")
    check("res: tight with room admits a heavy spawn", admit({"code": 1, "room_heavy": 1}, True), True)
    check("res: no room holds a heavy spawn", admit({"code": 0, "room_heavy": 0}, True), False)
    check("res: closed still admits a light one", admit({"code": 2, "room_heavy": 0}, False), True)
    check("res: critical holds everything", admit({"code": 3, "room_heavy": 0}, False), False)
    check("res: size parser", (_size("11G"), _size("512K"), _size("123,456 K")), (11 * GB, 512 * 1024, 123456 * 1024))
    check("res: the watcher warning never advises ignore_dirs", "ignore_dirs" in judge(mac_bad, {}, ["/r/.claude/worktrees"])["warnings"][0], False)
    s = probe([os.getcwd()], top_n=3)
    check("res: probe reads this machine", bool(s.get("ram")) and s.get("cores", 0) >= 1, True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
