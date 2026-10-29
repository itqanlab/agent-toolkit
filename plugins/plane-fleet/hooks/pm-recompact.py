#!/usr/bin/env python3
"""
pm-recompact: SessionStart hook (matcher "compact", Claude Code). Puts a PM session back on its
feet right after it compacts.

The PM's context grows about 1.3k tokens a call: a median 177k early in a session, 650k by call
400, and calls over 400k were 48% of PM spend (measured 2026-10-25). Starting the PM with
`claude --autocompact 300k` keeps it near 300k, but a compaction summary is lossy. This hook
adds the real fleet state (`fleet status`) and the PM's few hard rules to the compacted
context, so the PM continues from facts instead of from the summary.

It acts only in a PM session: one whose transcript shows the PM role. Anything it prints
on stdout becomes context; it prints nothing elsewhere and never fails the session.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET = os.path.normpath(os.path.join(HERE, "..", "skills", "plane-fleet"))
MARKERS = ("core/pm/role.md", "/plane-fleet run", "roles/team-pm/SKILL.md", "/team-pm", "team-pm:")  # old names: sessions from before 2.0
SCAN_BYTES = 64 * 1024 * 1024

RULES = """\
You are the fleet PM, and this session was just compacted. The summary above is lossy;
the fleet state below is current. Before the next pick:
- If the PM rules are no longer in your context, re-read {fleet}/core/pm/role.md
  (only the sections you need) and {fleet}/engineering/references/standing-brief.md.
- Ticket states come from Plane (MCP), not from the summary. Slots held by live sessions,
  open PRs and CI come from the status below; run `{fleet}/core/scripts/fleet status`
  again before every pick.
- Hard rules: never read code, run builds or tests yourself; one slot per live session; never
  merge without Approved + qa-approved + required checks green; log every spawn with its
  agent_id; a verify_fail needs --cause; spawn nothing heavy unless the `machine:` line says
  ok or tight with room, and at critical free memory first (spawn-tester.md, machine gate).
"""


def is_pm_session(transcript):
    """True when the transcript shows the PM role. Reads at most SCAN_BYTES."""
    if not transcript or not os.path.exists(transcript):
        return False
    read = 0
    with open(transcript, errors="replace") as f:
        for line in f:
            read += len(line)
            if any(m in line for m in MARKERS):
                return True
            if read > SCAN_BYTES:
                return False
    return False


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    if event.get("source") not in (None, "compact") or not is_pm_session(event.get("transcript_path")):
        return 0
    status = ""
    try:
        r = subprocess.run([os.path.join(FLEET, "core", "scripts", "fleet"), "status"],
                           cwd=event.get("cwd") or os.getcwd(), capture_output=True, text=True, timeout=50)
        status = r.stdout.strip() or ("status failed: " + r.stderr.strip()[-300:])
    except Exception as e:
        status = f"status failed: {e}"
    print(RULES.format(fleet=FLEET) + "\n" + status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
