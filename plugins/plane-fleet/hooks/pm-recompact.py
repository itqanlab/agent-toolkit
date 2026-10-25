#!/usr/bin/env python3
"""
pm-recompact: SessionStart hook (matcher "compact", Claude Code). Puts a PM session back on its
feet right after it compacts.

The PM's context grows about 1.3k tokens a call: a median 177k early in a session, 650k by call
400, and calls over 400k were 48% of PM spend (measured 2026-10-25). Starting the PM with
`claude --autocompact 300k` keeps it near 300k, but a compaction summary is lossy. This hook
adds the real fleet state (`run-lane.sh status`) and the PM's few hard rules to the compacted
context, so the PM continues from facts instead of from the summary.

It acts only in a PM session: one whose transcript shows the team-pm role. Anything it prints
on stdout becomes context; it prints nothing elsewhere and never fails the session.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET = os.path.normpath(os.path.join(HERE, "..", "skills", "plane-fleet"))
MARKERS = ("roles/team-pm/SKILL.md", "/team-pm", "team-pm:")
SCAN_BYTES = 64 * 1024 * 1024

RULES = """\
You are the plane-fleet PM, and this session was just compacted. The summary above is lossy;
the fleet state below is current. Before the next pick:
- If the team-pm rules are no longer in your context, re-read {fleet}/roles/team-pm/SKILL.md
  (only the sections you need) and {fleet}/references/standing-brief.md.
- Ticket states come from Plane (MCP), not from the summary. Slots held by live sessions,
  open PRs and CI come from the status below; run `{fleet}/scripts/lanes/run-lane.sh status`
  again before every pick.
- Hard rules: never read code, run builds or tests yourself; one slot per live session; never
  merge without Approved + qa-approved + required checks green; log every spawn with its
  agent_id; a verify_fail needs --cause.
"""


def is_pm_session(transcript):
    """True when the transcript shows the team-pm role. Reads at most SCAN_BYTES."""
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
        r = subprocess.run([os.path.join(FLEET, "scripts", "lanes", "run-lane.sh"), "status"],
                           cwd=event.get("cwd") or os.getcwd(), capture_output=True, text=True, timeout=50)
        status = r.stdout.strip() or ("status failed: " + r.stderr.strip()[-300:])
    except Exception as e:
        status = f"status failed: {e}"
    print(RULES.format(fleet=FLEET) + "\n" + status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
