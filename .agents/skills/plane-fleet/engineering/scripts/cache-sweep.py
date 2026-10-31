#!/usr/bin/env python3
"""cache-sweep.py — find (and with --apply, delete) the temp and cache folders fleet work leaves
behind on the machine's disk. Called by `fleet-sweep.sh --caches`; run it weekly.

DRY RUN IS THE DEFAULT. Without --apply nothing is deleted: it prints what it would remove and
how much space that frees. Delete only with --apply.

What it looks at (all paths from the merged project config, `fleet.tool_caches`; every key optional):
  tmpdir              the temp dir lanes run with (TMPDIR). Default: the OS temp dir.
  temp_globs          fleet temp folders. Default: <tmpdir>/tmp-*  and  /tmp/<plane identifier>-*
                      (the identifier as written, e.g. /tmp/PROJ-*). Removed when nothing inside changed for --max-age-days (7).
  nx_temp_regex       Nx socket folders directly under tmpdir. Default: ^[0-9a-f]{20}$
                      Same age rule.
  jest_cache_globs    Jest caches. Default: <tmpdir>/jest_*. Removed whole, once over
  jest_cache_max_gb   (default 5) GB, and only while no Jest process runs. Jest rebuilds it.
  docker_build_cache  true (default) to prune Docker's BUILD cache older than the age limit.
                      Never images, containers or volumes. Skipped when docker is absent.

Safety, in this order, for every folder before it is removed:
  - it is a real directory, not a symlink
  - it resolves under an allowed root: the configured tmpdir, the OS temp dir, /tmp, /private/tmp
  - it is at least one level below that root, and is neither the repo, a worktree, nor the home dir
  - it matches the pattern it was found by
  - nothing inside it was modified within the age limit (Jest: nothing is running instead)
A folder that fails any check is listed as skipped, with the reason, and left alone.

Exit: 0 done (or dry run listed), 3 usage error.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, tempfile, time

GB = 1024 ** 3
HERE = os.path.dirname(os.path.realpath(__file__))


def fleet_config(repo):
    r = subprocess.run([os.path.join(HERE, "..", "..", "core", "scripts", "fleet"), "config", "--cwd", repo],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {}


def expand(p):
    return os.path.expanduser(os.path.expandvars(p))


def newest_mtime(path, stop_after):
    """Newest mtime under path; stops early once something newer than stop_after is seen."""
    newest = os.lstat(path).st_mtime
    for root, dirs, files in os.walk(path, followlinks=False):
        for n in dirs + files:
            try:
                m = os.lstat(os.path.join(root, n)).st_mtime
            except OSError:
                continue
            newest = max(newest, m)
            if newest > stop_after:
                return newest
    return newest


def du_bytes(path):
    r = subprocess.run(["du", "-sk", path], capture_output=True, text=True)
    try:
        return int(r.stdout.split()[0]) * 1024
    except (ValueError, IndexError):
        return 0


def jest_running():
    r = subprocess.run(["pgrep", "-f", r"node.*[/ ]jest( |$)|jest-worker|jest/bin/jest"], capture_output=True, text=True)
    me = str(os.getpid())
    return [p for p in r.stdout.split() if p != me]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--apply", action="store_true", help="delete; without it this is a dry run")
    ap.add_argument("--max-age-days", type=float, default=7)
    a = ap.parse_args()
    repo = os.path.realpath(a.repo)
    cfg = fleet_config(repo)
    tc = (cfg.get("fleet") or {}).get("tool_caches") or {}
    ident = (cfg.get("plane") or {}).get("identifier") or ""

    tmpdir = os.path.realpath(expand(tc["tmpdir"])) if tc.get("tmpdir") else os.path.realpath(tempfile.gettempdir())
    roots = sorted({tmpdir, os.path.realpath(tempfile.gettempdir()), os.path.realpath("/tmp")})
    protected = [repo, os.path.realpath(os.path.expanduser("~"))]
    try:
        wt = subprocess.run(["git", "-C", repo, "worktree", "list", "--porcelain"], capture_output=True, text=True).stdout
        protected += [os.path.realpath(l[9:]) for l in wt.splitlines() if l.startswith("worktree ")]
    except OSError:
        pass
    cutoff = time.time() - a.max_age_days * 86400

    def under_root(rp):
        return any(rp.startswith(r + os.sep) for r in roots)

    def safe(path, pattern_ok):
        if os.path.islink(path) or not os.path.isdir(path):
            return "not a real directory"
        rp = os.path.realpath(path)
        if not under_root(rp):
            return "outside the allowed temp roots"
        if any(rp == p or p.startswith(rp + os.sep) for p in protected):
            return "contains or is a repo, worktree or home dir"
        if not pattern_ok:
            return "does not match its pattern"
        return None

    temp_globs = [expand(g) for g in tc.get("temp_globs") or []]
    if not temp_globs:
        temp_globs = [os.path.join(tmpdir, "tmp-*")]
        if ident:
            for base in ("/tmp", "/private/tmp"):
                temp_globs += [os.path.join(base, f"{ident}-*")]
    nx_re = re.compile(tc.get("nx_temp_regex") or r"^[0-9a-f]{20}$")
    jest_globs = [expand(g) for g in tc.get("jest_cache_globs") or []] or [os.path.join(tmpdir, "jest_*")]
    jest_max = float(tc.get("jest_cache_max_gb", 5)) * GB

    plan, skipped, seen = [], [], set()

    def consider(kind, path, why_keep=None, extra=None):
        if not os.path.isdir(path) or os.path.islink(path):
            return  # only real folders are ever candidates; plain files are not listed
        rp = os.path.realpath(path)
        if rp in seen:
            return
        seen.add(rp)
        plan.append((kind, path, why_keep, extra))

    for g in temp_globs:
        for p in glob.glob(g):
            consider("temp", p)
    try:
        for n in os.listdir(tmpdir):
            if nx_re.match(n):
                consider("nx", os.path.join(tmpdir, n))
    except OSError:
        pass
    for g in jest_globs:
        for p in glob.glob(g):
            consider("jest", p)

    freed, removed = 0, 0
    running = jest_running()
    for kind, path, _, _ in plan:
        reason = safe(path, True)
        if reason:
            skipped.append((path, reason)); continue
        if kind == "jest":
            size = du_bytes(path)
            if size <= jest_max:
                continue
            if running:
                skipped.append((path, f"{size / GB:.1f} GB but Jest is running (pids {' '.join(running[:3])})")); continue
        else:
            if newest_mtime(path, cutoff) > cutoff:
                continue
            size = du_bytes(path)
        verb = "removed" if a.apply else "would remove"
        label = {"temp": "fleet temp", "nx": "Nx temp", "jest": "Jest cache"}[kind]
        print(f"  {verb:12} {size / GB:7.2f} GB  {label:10} {path}")
        if a.apply:
            shutil.rmtree(path, ignore_errors=True)
        freed += size; removed += 1

    docker_note = None
    if tc.get("docker_build_cache", True) and shutil.which("docker"):
        hours = int(a.max_age_days * 24)
        df = subprocess.run(["docker", "system", "df", "--format", "{{.Type}}\t{{.Size}}\t{{.Reclaimable}}"],
                            capture_output=True, text=True, timeout=30)
        line = next((l for l in df.stdout.splitlines() if l.startswith("Build Cache")), "")
        if df.returncode != 0:
            docker_note = "docker is not answering; build cache skipped"
        elif a.apply:
            r = subprocess.run(["docker", "builder", "prune", "--force", "--filter", f"until={hours}h"], capture_output=True, text=True, timeout=600)
            docker_note = f"docker build cache pruned (older than {hours}h): " + (r.stdout.strip().splitlines() or ["done"])[-1]
        else:
            docker_note = f"would prune docker build cache older than {hours}h ({line.replace(chr(9), ' / ')})"

    for path, reason in skipped:
        print(f"  skipped      {path} :: {reason}")
    if docker_note:
        print(f"  {docker_note}")
    mode = "applied" if a.apply else "DRY RUN, nothing deleted (add --apply to delete)"
    print(f"sweep: {mode} · {removed} folder(s) · {freed / GB:.2f} GB · roots {', '.join(roots)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
