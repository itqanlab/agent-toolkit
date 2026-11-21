#!/usr/bin/env python3
"""PreToolUse guard for unattended fleet runs (`fleet schedule`, core/references/unattended.md).

Active only when FLEET_UNATTENDED=1, which `fleet schedule run-once` sets for the run it starts.
In an attended session it does nothing.

Never allowed unattended, whatever the config says:
  - a push to, a merge into, or a PR against a production branch (deploy.environments with
    name "prod" or "production", plus git.prod_branch), and a release tag.
  - running a deploy command of a production environment.
Allowed only when listed in fleet.unattended.allow:
  - "merge":           gh pr merge (into the trunk)
  - "client_message":  the client channel skill or tool (client.channel)
Everything else (build, test, PRs into the trunk, Plane writes) is left to the normal rules.

Answers the hook protocol: exit 0 with no output to allow; a JSON "deny" decision to block, with
a reason the model reads, so the run goes on and records the blocked step for the owner.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROD_NAMES = ("prod", "production")


def prod_branches(cfg):
    out = set()
    for env in ((cfg.get("deploy") or {}).get("environments") or []):
        if str(env.get("name", "")).lower() in PROD_NAMES and env.get("branch"):
            out.add(str(env["branch"]))
    if (cfg.get("git") or {}).get("prod_branch"):
        out.add(str(cfg["git"]["prod_branch"]))
    return out


def prod_commands(cfg):
    out = []
    for env in ((cfg.get("deploy") or {}).get("environments") or []):
        if str(env.get("name", "")).lower() in PROD_NAMES:
            for key in ("deploy_command", "command"):
                if env.get(key):
                    out.append(str(env[key]))
    return out


def pr_base(number, cwd):
    try:
        p = subprocess.run(["gh", "pr", "view", *([str(number)] if number else []), "--json", "baseRefName", "-q", ".baseRefName"],
                           capture_output=True, text=True, cwd=cwd, timeout=20)
        return p.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def decide(tool, tool_input, cfg, base_of=None, cwd=None):
    """None to allow, or the reason to deny."""
    unat = ((cfg.get("fleet") or {}).get("unattended") or {})
    allow = set(unat.get("allow") or [])
    prod = prod_branches(cfg)
    base_of = base_of or (lambda n: pr_base(n, cwd))
    nobody = "This is an unattended run: "
    if tool == "Bash":
        cmd = str((tool_input or {}).get("command") or "")
        for branch in prod:
            b = re.escape(branch)
            if re.search(rf"\bgit\s+push\b[^\n;&|]*(?:\s|:|/){b}(?:\s|$|[;&|])", cmd):
                return f"{nobody}pushing to the production branch `{branch}` waits for the owner."
            if re.search(rf"\bgh\s+pr\s+create\b[^\n;&|]*--base[\s=]+{b}\b", cmd):
                return f"{nobody}a PR into the production branch `{branch}` waits for the owner."
        if prod and re.search(r"\bgit\s+tag\b", cmd) and re.search(r"\bgit\s+push\b[^\n;&|]*--tags|\bgit\s+push\b[^\n;&|]*\bv?\d+\.\d+", cmd):
            return f"{nobody}pushing a release tag waits for the owner."
        for pc in prod_commands(cfg):
            if pc and pc in cmd:
                return f"{nobody}the production deploy command waits for the owner."
        m = re.search(r"\bgh\s+pr\s+merge\b\s*(\d+)?", cmd)
        if m:
            if "merge" not in allow:
                return f"{nobody}merging is not in fleet.unattended.allow. Leave the PR approved for the owner."
            number = m.group(1)
            label = f"PR #{number}" if number else "this branch's PR"
            base = base_of(number)
            if base is None:
                return f"{nobody}could not read {label}'s base branch, so it is not merged unattended."
            if base in prod:
                return f"{nobody}{label} targets the production branch `{base}`; it waits for the owner."
        return None
    channel = str((cfg.get("client") or {}).get("channel") or "")
    if channel and channel != "none" and "client_message" not in allow:
        name = tool if tool != "Skill" else str((tool_input or {}).get("skill") or "")
        if channel in name:
            return f"{nobody}client messages are not in fleet.unattended.allow. Write the message into the resume note instead."
    return None


def load_cfg(cwd):
    sys.path.insert(0, os.path.join(HERE, "..", "skills", "plane-fleet", "core", "scripts"))
    try:
        import fleetctl
        return fleetctl.project_config(cwd) or {}
    except Exception:
        return {}


def main():
    if os.environ.get("FLEET_UNATTENDED") != "1":
        return 0
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    cwd = event.get("cwd") or os.getcwd()
    reason = decide(event.get("tool_name"), event.get("tool_input"), load_cfg(cwd), cwd=cwd)
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    return 0


def selftest(check):
    cfg = {"git": {"trunk": "develop"},
           "deploy": {"environments": [{"name": "dev", "branch": "develop"},
                                       {"name": "prod", "branch": "main", "deploy_command": "scripts/deploy-prod.sh"}]},
           "client": {"channel": "whatsapp-send"},
           "fleet": {"unattended": {"allow": ["merge"]}}}
    bases = {"12": "develop", "13": "main"}
    d = lambda tool, inp, c=cfg: decide(tool, inp, c, base_of=lambda n: bases.get(n))
    check("guard: push to the trunk allowed", d("Bash", {"command": "git push origin develop"}), None)
    check("guard: push to prod denied", bool(d("Bash", {"command": "git push origin main"})), True)
    check("guard: push HEAD:main denied", bool(d("Bash", {"command": "git push origin HEAD:main"})), True)
    check("guard: a branch named main-fix is not prod", d("Bash", {"command": "git push origin main-fix"}), None)
    check("guard: PR into prod denied", bool(d("Bash", {"command": "gh pr create --base main --title x"})), True)
    check("guard: PR into the trunk allowed", d("Bash", {"command": "gh pr create --base develop --title x"}), None)
    check("guard: merge into the trunk allowed when listed", d("Bash", {"command": "gh pr merge 12 --merge"}), None)
    check("guard: merge into prod denied", bool(d("Bash", {"command": "gh pr merge 13 --merge"})), True)
    check("guard: merge with an unreadable base denied", bool(d("Bash", {"command": "gh pr merge 99 --merge"})), True)
    no_merge = {**cfg, "fleet": {"unattended": {"allow": []}}}
    check("guard: merge denied when not listed", bool(d("Bash", {"command": "gh pr merge 12"}, no_merge)), True)
    check("guard: the prod deploy command denied", bool(d("Bash", {"command": "bash scripts/deploy-prod.sh --yes"})), True)
    check("guard: a release tag push denied", bool(d("Bash", {"command": "git tag v1.2.0 && git push origin --tags"})), True)
    check("guard: client message denied when not listed", bool(d("Skill", {"skill": "whatsapp-send"})), True)
    yes_msg = {**cfg, "fleet": {"unattended": {"allow": ["merge", "client_message"]}}}
    check("guard: client message allowed when listed", d("Skill", {"skill": "whatsapp-send"}, yes_msg), None)
    check("guard: merge of the current branch's PR into prod denied",
          bool(decide("Bash", {"command": "gh pr merge --merge"}, cfg, base_of=lambda n: "main")), True)
    check("guard: merge of the current branch's PR into the trunk allowed",
          decide("Bash", {"command": "gh pr merge --merge"}, cfg, base_of=lambda n: "develop"), None)
    check("guard: ordinary commands allowed", d("Bash", {"command": "npx nx test client"}), None)


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        ok = [True]
        def check(name, got, want):
            ok[0] &= got == want
            print(f"{'ok  ' if got == want else 'FAIL'} {name}: {got!r}" + ("" if got == want else f" (want {want!r})"))
        selftest(check)
        sys.exit(0 if ok[0] else 1)
    sys.exit(main())
