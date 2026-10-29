#!/usr/bin/env python3
"""
usage-pacer: PreToolUse hook on the Agent tool (Claude Code). Gates spawns of fleet roles on
the Claude budget. It is the Claude half of the fleet's per-executor pacer: the rules (hard
stop, pace allowance, stale meter, switch files) live in fleetctl.py, which the fleet command also
asks before it starts a Codex or opencode lane. Same thresholds for every executor.

Meter: the file named by budget.executors.claude.status_file (a statusline relay that writes
the harness's rate_limits.five_hour block). No meter configured -> no judgement.

  1. Hard stop at hard_stop_pct (default 95): no new fleet session.
  2. Pace: no faster than the window elapses plus pace_allowance_pct (default 20).

Blocking = exit 2 with the reason on stderr. Decisions go to pacer-log.jsonl in
PLANE_FLEET_HOME (default ~/.config/plane-fleet), or budget.executors.claude.pacer_log.

It also holds a spawn the machine cannot carry (fleetres.py, any OS): an engineer or tester
needs the resource gate ok or tight with room for one more heavy session; other fleet roles are
held only when it is critical. Switch file: resources-off.

Switch files in PLANE_FLEET_HOME: pacer-off / pacer-off-claude (no gate), pace-off /
pace-off-claude (hard stop only). Thresholds: the registry's budget block, overridden in
PLANE_FLEET_HOME/budget.json.
"""
import json, os, sys, time, datetime

HERE = os.path.dirname(os.path.realpath(__file__))
STATE_HOME = os.environ.get("PLANE_FLEET_HOME") or os.path.expanduser("~/.config/plane-fleet")
# A general-purpose spawn is a fleet role when its prompt names the role file (old names: before 2.0).
FLEET = {"engineering/engineer/role.md": "team-engineer", "engineering/tester/role.md": "team-tester",
         "core/planner/skills/write-ticket.md": "team-ticket-writer",
         "team-engineer": "team-engineer", "team-tester": "team-tester", "team-ticket-writer": "team-ticket-writer"}
# Agent types spawned by subagent_type; logged under the role they run so history stays comparable.
FLEET_AGENTS = {"fleet-engineer": "team-engineer", "fleet-tester": "team-tester",
                "fleet-planner": "fleet-planner", "fleet-board": "fleet-board", "fleet-plane": "fleet-board",
                "fleet-scanner": "fleet-scanner"}
LANES_DIRS = [d for d in (
    os.environ.get("FLEETCTL_DIR"),
    os.path.join(HERE, "..", "skills", "plane-fleet", "core", "scripts"),
) if d]


def hhmm(epoch):
    return datetime.datetime.fromtimestamp(epoch).astimezone().strftime("%H:%M %Z")


def log(path, row):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def resources_hold(role):
    """A reason to hold this spawn on machine resources, or None."""
    if os.path.exists(os.path.join(STATE_HOME, "resources-off")):
        return None
    try:
        sys.path[:0] = LANES_DIRS
        import fleetres  # noqa
        cfg, paths, wdirs = fleetres.context(os.getcwd())
        sample = fleetres.probe(paths, top_n=8)
        gate = fleetres.judge(sample, cfg, wdirs)
    except Exception:
        return None  # no probe available: the PM's own sweep still runs
    heavy = role in ("team-engineer", "team-tester")
    if fleetres.admit(gate, heavy):
        return None
    hogs = "; ".join(f"{h['name']} {h['mem_gb']} GB ({h.get('fix', 'find its owner')})" for h in gate["hogs"] if not h["fleet"])
    return (f"resource gate: machine is {gate['level'].upper()} ({fleetres.summary_line(sample, gate)}). Do not start a new "
            f"{role} session. " + ("; ".join(gate["reasons"]) + ". ") +
            (f"Biggest non-fleet processes: {hogs}. " if hogs else "") +
            "Run `fleet resources`, apply the safe fixes, sweep leftovers, and let running sessions finish. "
            f"Override once only on the owner's word: touch {STATE_HOME}/resources-off.")


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    tool_input = event.get("tool_input", {})
    prompt = json.dumps(tool_input)
    # a plugin install names agents <plugin>:<section>:<agent>
    role = FLEET_AGENTS.get(str(tool_input.get("subagent_type", "")).split(":")[-1]) \
        or next((v for k, v in FLEET.items() if k in prompt), None)
    if not role:
        return 0
    held = resources_hold(role)
    if held:
        print(held, file=sys.stderr)
        return 2
    now = time.time()
    try:
        sys.path[:0] = LANES_DIRS
        import fleetctl  # noqa
        reg = fleetctl.load_registry(os.getcwd())
        check = fleetctl.budget_check(reg, "claude", now)
        line = fleetctl.budget_line(reg)
        log_path = os.environ.get("USAGE_PACER_LOG") or fleetctl.X(
            fleetctl.budget_cfg(reg, "claude").get("pacer_log") or os.path.join(STATE_HOME, "pacer-log.jsonl"))
    except Exception:
        return 0  # no pacer available: the skill's own budget rules still apply
    row = {"ts": datetime.datetime.utcnow().isoformat() + "Z", "role": role, "used": check.get("used_pct"),
           "resets_at": check.get("resets_at"), "note": check.get("note")}
    if check["used_pct"] is None and check["state"] == "ok":
        return 0  # unknown meter: no judgement
    portable = (" Portable work (engineers, scans) can go to a Codex or opencode lane instead: "
                "`fleet pick` only offers executors with budget.") if role == "team-engineer" else ""
    tail = f" Budget: {line}." if line else ""
    if check["state"] == "stop":
        row["decision"] = "hard-stop"
        log(log_path, row)
        print(f"usage-pacer: Claude 5-hour usage is {check['used_pct']:.0f}% (hard stop). Resets at "
              f"{hhmm(check['resume_at'] or check['resets_at'])}. Do not start a new {role} Claude session. Land what "
              f"is verified, keep the resume note current, and pick up after the reset.{portable}{tail}", file=sys.stderr)
        return 2
    if check["state"] == "hold":
        row["decision"] = "ahead-of-pace" if "pace" in (check.get("note") or "") else "hold"
        log(log_path, row)
        used = f"{check['used_pct']:.0f}% used" if check.get("used_pct") is not None else "held"
        print(f"usage-pacer: Claude {used} ({check.get('note')}). Hold new {role} Claude sessions until about "
              f"{hhmm(check['resume_at'])}. Meanwhile keep merging, testing what is open and writing the board: "
              f"those cost little.{portable}{tail}", file=sys.stderr)
        return 2
    row["decision"] = "allow"
    log(log_path, row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
