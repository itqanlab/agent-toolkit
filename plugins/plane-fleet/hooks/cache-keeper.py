#!/usr/bin/env python3
"""
cache-keeper: PreToolUse hook on Bash and Monitor (Claude Code). Keeps every wait inside a fleet
agent shorter than the agent's prompt cache, which lives 5 minutes.

A call that blocks longer lets the cache expire, and the agent's next call writes its whole
context again at 1.25x the input price. Measured 2026-10-25 on one project: 637 such rewrites
in a month, $529 or 12% of agent spend, almost all after a sleep loop, an e2e run or a build
the agent waited on for 8 to 10 minutes. A check every 4 minutes costs one cache read instead.

Only fleet agents are held: the hook input's agent_type is fleet-engineer, fleet-tester,
fleet-planner or fleet-plane (a plugin install may prefix it, as plane-fleet:fleet-engineer).
The main session and every other agent pass untouched.

  Bash:    a foreground call with a timeout over 270000 ms is refused. Run it in the background
           and check it with waits of at most 240 s.
  Monitor: a timeout_ms over 270000, or none (the default is 300000), is refused.

Refusals go back to the agent as the reason, and to cache-keeper.jsonl in PLANE_FLEET_HOME
(default ~/.config/plane-fleet). Switch file cache-keeper-off in PLANE_FLEET_HOME turns it off.
"""
import json, os, sys, time

STATE_HOME = os.environ.get("PLANE_FLEET_HOME") or os.path.expanduser("~/.config/plane-fleet")
FLEET_AGENTS = ("fleet-engineer", "fleet-tester", "fleet-planner", "fleet-plane")
LIMIT_MS = 270000
WHY = ("The prompt cache of this session lives 5 minutes. A call that waits longer makes the next "
       "call write the whole context again (measured: 12% of fleet agent spend).")


def is_fleet_agent(agent_type):
    return bool(agent_type) and agent_type.split(":")[-1] in FLEET_AGENTS


def verdict(event):
    """None to allow, or the reason to refuse."""
    if not is_fleet_agent(event.get("agent_type")):
        return None
    tool, inp = event.get("tool_name"), event.get("tool_input") or {}
    if tool == "Bash":
        if inp.get("run_in_background"):
            return None
        try:
            t = float(inp.get("timeout") or 0)
        except (TypeError, ValueError):
            return None
        if t > LIMIT_MS:
            return (f"{WHY} Keep a foreground Bash timeout at {LIMIT_MS} ms or less. For a longer job "
                    "(an e2e suite, a build, a server coming up) run it with run_in_background: true, then "
                    "check its output or the port with waits of at most 240 s each, until it is done.")
    elif tool == "Monitor":
        try:
            t = float(inp.get("timeout_ms") or 0)
        except (TypeError, ValueError):
            t = 0
        if not t or t > LIMIT_MS:
            return (f"{WHY} Give Monitor a timeout_ms of {LIMIT_MS} or less (its default is 300000). If "
                    "the event has not come by then, check once and wait again.")
    return None


def main():
    if os.path.exists(os.path.join(STATE_HOME, "cache-keeper-off")):
        return 0
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    reason = verdict(event)
    if not reason:
        return 0
    try:
        os.makedirs(STATE_HOME, exist_ok=True)
        with open(os.path.join(STATE_HOME, "cache-keeper.jsonl"), "a") as f:
            inp = event.get("tool_input") or {}
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "agent_type": event.get("agent_type"),
                                "agent_id": event.get("agent_id"), "tool": event.get("tool_name"),
                                "timeout": inp.get("timeout") or inp.get("timeout_ms"), "cwd": event.get("cwd")}) + "\n")
    except OSError:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
