#!/usr/bin/env python3
"""fleet cache-server: one Nx cache for every worktree of a project on this machine.

Nx 22 keeps a database next to each worktree's local cache and ignores cache entries that
database did not write, so pointing two worktrees at one cache folder gives no hits. Nx 20.8+
also talks to a self-hosted remote cache over a small HTTP API (PUT/GET /v1/cache/{hash},
bearer token). This file is that server, bound to 127.0.0.1, storing tar files on disk.
Every engineer, tester and group worktree that exports the env lines below reuses the
others' lint, typecheck, unit-test and build results when the inputs are the same.

  fleet cache-server start  [--cwd REPO]   start it for the repo's project (no-op if running)
  fleet cache-server stop   [--cwd REPO]
  fleet cache-server status [--cwd REPO] [--json]   running?, entries, size, hits and misses
  fleet cache-server env    [--cwd REPO]   export lines for a shell; starts the server when
                                           enabled; prints nothing when off, so
                                           `eval "$(fleet cache-server env --cwd .)"` is always safe
  fleet cache-server serve --dir D --port P --token-file F [--max-gb N]   (foreground; start uses it)

Config, all optional, under fleet.nx_cache_server in .plane/config.json or the user override:
  {"enabled": true, "port": 4590, "dir": "<path>", "max_gb": 20}
  dir defaults to <fleet.tool_caches.tmpdir or ~/.cache/plane-fleet>/nx-remote-cache/<project>.
  Oldest entries (by last read) are dropped once the folder passes max_gb.

What it never changes: which targets Nx caches. That is the repo's nx.json. Targets that hit a
database (e2e) must stay uncached there; the server cannot tell targets apart.
"""
import argparse
import hmac
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_HOME = os.environ.get("PLANE_FLEET_HOME") or os.path.expanduser("~/.config/plane-fleet")
HASH_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
DEFAULT_PORT = 4590
GB = 1024 ** 3


# ---------------------------------------------------------------- server
class Store:
    def __init__(self, root, max_bytes):
        self.root, self.max_bytes = root, max_bytes
        os.makedirs(root, exist_ok=True)
        self.lock = threading.Lock()
        self.stats = {"hits": 0, "misses": 0, "puts": 0, "conflicts": 0, "evicted": 0, "started": int(time.time())}
        for n in os.listdir(root):          # a crash mid-upload leaves a .part; drop it
            if n.endswith(".part"):
                try: os.remove(os.path.join(root, n))
                except OSError: pass
        self.total = sum(self._size(n) for n in os.listdir(root))

    def _size(self, n):
        try: return os.path.getsize(os.path.join(self.root, n))
        except OSError: return 0

    def path(self, h):
        return os.path.join(self.root, h)

    def evict(self):
        if self.total <= self.max_bytes:
            return
        with self.lock:
            files = []
            for n in os.listdir(self.root):
                if n.endswith(".part"):
                    continue
                p = os.path.join(self.root, n)
                try:
                    st = os.stat(p); files.append((st.st_mtime, st.st_size, p))
                except OSError:
                    pass
            files.sort()
            target = int(self.max_bytes * 0.8)
            for _, size, p in files:
                if self.total <= target:
                    break
                try:
                    os.remove(p); self.total -= size; self.stats["evicted"] += 1
                except OSError:
                    pass


def make_handler(store, token):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", ctype="text/plain"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)

        def _authed(self):
            got = self.headers.get("Authorization", "")
            return hmac.compare_digest(got.encode(), f"Bearer {token}".encode())

        def _hash(self):
            m = re.match(r"^/v1/cache/([^/?]+)$", self.path)
            return m.group(1) if m and HASH_RE.match(m.group(1)) else None

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, b"ok")
            if not self._authed():
                return self._send(401, b"missing or invalid token")
            if self.path == "/stats":
                s = dict(store.stats, bytes=store.total, max_bytes=store.max_bytes,
                         entries=sum(1 for n in os.listdir(store.root) if not n.endswith(".part")))
                return self._send(200, json.dumps(s).encode(), "application/json")
            h = self._hash()
            if not h:
                return self._send(404)
            p = store.path(h)
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except FileNotFoundError:
                store.stats["misses"] += 1
                return self._send(404)
            try: os.utime(p)                 # last read decides eviction order
            except OSError: pass
            store.stats["hits"] += 1
            self._send(200, data, "application/octet-stream")

        def do_PUT(self):
            if not self._authed():
                return self._send(401, b"missing or invalid token")
            h = self._hash()
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._send(411, b"Content-Length required")
            if not h:
                self.rfile.read(n)
                return self._send(400, b"bad hash")
            p = store.path(h)
            if os.path.exists(p):           # entries are immutable, as the spec asks
                self.rfile.read(n)
                store.stats["conflicts"] += 1
                return self._send(409)
            tmp = f"{p}.{secrets.token_hex(4)}.part"
            left = n
            with open(tmp, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk); left -= len(chunk)
            if left:
                os.remove(tmp)
                return self._send(400, b"short body")
            try:
                os.link(tmp, p)             # fails if another upload of the same hash won
                store.total += n; store.stats["puts"] += 1
            except FileExistsError:
                store.stats["conflicts"] += 1
                os.remove(tmp)
                return self._send(409)
            os.remove(tmp)
            store.evict()
            self._send(200)
    return H


def serve(d, port, token, max_gb, ready=None):
    store = Store(d, int(max_gb * GB))
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, token))
    srv.daemon_threads = True
    if ready is not None:
        ready.append(srv)
    srv.serve_forever()


# ---------------------------------------------------------------- control
def settings(cwd):
    sys.path.insert(0, HERE)
    import fleetctl
    cfg = (fleetctl.project_config(cwd or os.getcwd()) or {}).get("fleet") or {}
    project = fleetctl.project_of(cwd or os.getcwd())
    s = cfg.get("nx_cache_server") or {}
    base = os.path.expanduser(os.path.expandvars(((cfg.get("tool_caches") or {}).get("tmpdir")) or "~/.cache/plane-fleet"))
    d = os.path.expanduser(os.path.expandvars(s.get("dir") or os.path.join(base, "nx-remote-cache", project)))
    state = os.path.join(STATE_HOME, "nx-cache", project)
    return {"enabled": bool(s.get("enabled")), "port": int(s.get("port") or DEFAULT_PORT), "dir": d,
            "max_gb": float(s.get("max_gb") or 20), "state": state, "project": project}


def token_of(state):
    p = os.path.join(state, "token")
    if not os.path.exists(p):
        os.makedirs(state, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(24))
    return open(p).read().strip()


def healthy(port, timeout=1.0):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def start(s, quiet=False):
    if healthy(s["port"]):
        if not quiet:
            print(f"cache-server: running on 127.0.0.1:{s['port']} ({s['dir']})")
        return True
    token_of(s["state"])
    os.makedirs(s["dir"], exist_ok=True)
    log = open(os.path.join(s["state"], "server.log"), "a")
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "serve", "--dir", s["dir"], "--port", str(s["port"]),
                          "--token-file", os.path.join(s["state"], "token"), "--max-gb", str(s["max_gb"])],
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    with open(os.path.join(s["state"], "pid"), "w") as f:
        f.write(str(p.pid))
    for _ in range(50):
        if healthy(s["port"], 0.2):
            if not quiet:
                print(f"cache-server: started on 127.0.0.1:{s['port']} pid {p.pid} ({s['dir']}, max {s['max_gb']:g} GB)")
            return True
        if p.poll() is not None:
            break
        time.sleep(0.1)
    print(f"cache-server: did not start; see {s['state']}/server.log (port {s['port']} taken?)", file=sys.stderr)
    return False


def stop(s):
    pf = os.path.join(s["state"], "pid")
    try:
        pid = int(open(pf).read().strip())
        os.kill(pid, signal.SIGTERM)
        os.remove(pf)
        print(f"cache-server: stopped pid {pid}")
    except (OSError, ValueError):
        print("cache-server: not running")


def stats(s):
    if not healthy(s["port"]):
        return None
    req = urllib.request.Request(f"http://127.0.0.1:{s['port']}/stats",
                                 headers={"Authorization": f"Bearer {token_of(s['state'])}"})
    with urllib.request.urlopen(req, timeout=2) as r:
        return json.loads(r.read())


def env_lines(s):
    if not s["enabled"] or not start(s, quiet=True):
        return ""
    return (f"export NX_SELF_HOSTED_REMOTE_CACHE_SERVER=http://127.0.0.1:{s['port']}\n"
            f"export NX_SELF_HOSTED_REMOTE_CACHE_ACCESS_TOKEN={token_of(s['state'])}\n")


# ---------------------------------------------------------------- selftest
def selftest(check):
    import tempfile
    d = tempfile.mkdtemp(prefix="fleetcache-selftest-")
    tok = "t" * 16
    ready = []
    t = threading.Thread(target=serve, args=(d, 0, tok, 1e-6), kwargs={"ready": ready}, daemon=True)
    t.start()
    for _ in range(50):
        if ready: break
        time.sleep(0.05)
    srv = ready[0]; port = srv.server_address[1]

    def call(method, path, body=None, auth=True):
        h = {"Authorization": f"Bearer {tok}"} if auth else {}
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    try:
        check("cache: health needs no token", call("GET", "/health", auth=False)[0], 200)
        check("cache: no token is 401", call("GET", "/v1/cache/abc", auth=False)[0], 401)
        check("cache: unknown hash is 404", call("GET", "/v1/cache/abc")[0], 404)
        check("cache: put stores", call("PUT", "/v1/cache/abc", b"tar-bytes")[0], 200)
        check("cache: get returns the bytes", call("GET", "/v1/cache/abc"), (200, b"tar-bytes"))
        check("cache: a second put is 409", call("PUT", "/v1/cache/abc", b"other")[0], 409)
        check("cache: the first upload is kept", call("GET", "/v1/cache/abc")[1], b"tar-bytes")
        check("cache: a path-like hash is refused", call("GET", "/v1/cache/..%2fx")[0], 404)
        call("PUT", "/v1/cache/def", b"x" * 4096)     # over the tiny limit: oldest go
        st = json.loads(call("GET", "/stats")[1])
        check("cache: eviction keeps the folder under the limit", st["evicted"] >= 1, True)
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleet cache-server")
    ap.add_argument("action", choices=["start", "stop", "status", "env", "serve", "selftest"])
    ap.add_argument("--cwd"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--dir"); ap.add_argument("--port", type=int); ap.add_argument("--token-file"); ap.add_argument("--max-gb", type=float, default=20)
    a = ap.parse_args(argv)
    if a.action == "serve":
        serve(a.dir, a.port, open(a.token_file).read().strip(), a.max_gb)
        return 0
    if a.action == "selftest":
        bad = []
        def check(name, got, want):
            ok = got == want
            print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": got {got!r}, want {want!r}"))
            if not ok: bad.append(name)
        selftest(check)
        return 1 if bad else 0
    s = settings(a.cwd)
    if a.action == "start":
        return 0 if start(s) else 1
    if a.action == "stop":
        stop(s); return 0
    if a.action == "env":
        sys.stdout.write(env_lines(s)); return 0
    st = stats(s)
    if a.json:
        print(json.dumps({"enabled": s["enabled"], "port": s["port"], "dir": s["dir"], "running": st is not None, "stats": st}))
    elif st is None:
        print(f"cache-server: not running (enabled: {s['enabled']}, port {s['port']}, dir {s['dir']})")
    else:
        asked = st["hits"] + st["misses"]
        rate = f"{100 * st['hits'] / asked:.0f}%" if asked else "n/a"
        print(f"cache-server: running on 127.0.0.1:{s['port']} · {st['entries']} entries · "
              f"{st['bytes'] / GB:.2f} of {st['max_bytes'] / GB:g} GB · hits {st['hits']} misses {st['misses']} ({rate}) · "
              f"uploads {st['puts']} · evicted {st['evicted']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
