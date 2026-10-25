# PM · spawn-tester

> Part of the PM role (`core/pm/role.md`). Read it when a PR opens. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 4) Spawn a tester the moment a PR opens — no CI wait

The moment **any** engineer reports "In Review · PR #n" **with a clean review** (below), that
PR is testable. If any slot is free, spawn tester on it right away:

**Review gate before the tester.** The engineer runs `codex review` on its own diff before
pushing (`engineering/engineer/skills/open-pr.md` §4.3b) and reports it in the handoff. Before you spawn a tester, read
that one line of the handoff:
- no review line, or the last pass has an open P1 → back to the same engineer lane (resume it
  or start a new one with the finding). No tester yet.
- a P2 marked "not applicable" with a reason you disagree with → post a `PM SCOPE DECISION:`
  saying it must be fixed, and send it back.
- otherwise, spawn the tester. If you doubt the report, run
  `codex review --base origin/<trunk>` on the pushed branch yourself. It takes about 5 minutes
  and needs no slot.

The group review (`core/pm/skills/merge-queue.md` §5) still runs. It should only find what comes from combining branches.
When it finds a per-PR defect, log it as a review escape (`log add --reason "review escape: …"`):
a run of escapes means the per-PR review isn't working.

```
Agent(description: "tester PROJ-134", subagent_type: "fleet-tester", model: "opus",
      run_in_background: true,
      prompt: "Fleet folder: <fleet>. Test PROJ-134, PR #212, branch <b>. Slot: C. ...")
```

Pick the tester's executor the same way as an engineer's (`core/pm/skills/spawn.md` §3 Executors). Today's default is
claude `opus` (`sonnet` for copy/i18n-only), so this is usually the `Agent` call above. If the
registry or a project override names a lane, start it with `fleet --role tester`.

- **Do not wait for its CI.** CI runs on the PR while the tester works. It only gates the merge
  queue (`core/pm/skills/merge-queue.md` §5).
- **Order:** oldest `In Review` first; a PR that unblocks other queued work or holds files
  another ticket needs jumps ahead.
- Send ticket id, PR, branch and slot. **Never paste the diff, the PR body or the engineer's
  notes into the brief** — the tester's first phase is blind on purpose.

**When the tester reports:**

- `APPROVED` → ticket is `Approved`, PR labelled. Queue it for `core/pm/skills/merge-queue.md` §5. Free the slot.
- `REWORK` → ticket is `Rework`. You route it: it goes back through `core/pm/skills/pick.md` §2 like any pick, at its
  priority, to a **fresh engineer** on the same branch. Free the slot. A ticket sent to Rework
  twice → say so in the pick announcement and escalate the engineer to `opus`.
- The tester stopped because the ticket text changed after the build → scope is your call.
  Decide, comment the decision on the ticket, then either re-test or send to Rework.

**Sweep and memory gate, before every spawn and after every report.** Run
`engineering/scripts/fleet-sweep.sh --repo <repo> --live <slots in use, e.g. A,C,F>`. It lists what dead
or finished sessions left running (servers on slot ports of slots not in use, processes in
removed worktrees or other slots' scratch dirs, Nx daemons, headless Chromium older than 3
hours or tied to a free slot), lists other projects' servers under "not ours" (never touched;
tell the owner once), and prints the gate: swap % and free disk.
- Leftovers → rerun with `--kill`, and say in one line what was stopped.
- Gate CLOSED (exit 2: free memory under 25% or under 6 GB free disk; swap is shown but not gated, macOS keeps it allocated) → spawn nothing new, not even
  a tester; let running sessions finish and re-check after each report. Lower the slot count
  you fill (start at 4 on a 32 GB machine) until the gate stays open with every slot busy.
- A lane that died (timeout, ENOSPC) leaves its processes behind: sweep right after you
  clean its worktree. (2026-10-14: an Nx daemon from a dead Codex lane ran 3 hours, and a
  Playwright Chromium from another ran 4 hours; seven slots put 17 GB in swap, and swap on
  the system disk was half of why that disk hit 100%.)

**Slot rules that make parallel hold** (each learned from a real collision):

- Never assign the shared row. One slot, one live session. Reuse only after reported teardown.
- The session checks its slot is free before starting and stops if not. An occupied slot means a
  dead session leaked it: clean it (stop the process on the port, drop the slot DB, remove the
  worktree) before handing that slot out again.
- `NX_DAEMON=false` + a per-slot `NX_CACHE_DIRECTORY`. Separate ports and DBs are not enough:
  one slot's build restarted another slot's running API through the shared Nx daemon.
- A worktree needs its own real `node_modules` (`pnpm install --frozen-lockfile`) and its own
  built workspace libs. A worktree that resolves libraries through the main checkout tests the
  fix against the old compiled dependency.
- Each running slot is a server + client + Playwright on this machine. If the machine struggles
  (builds timing out, tests flaking), lower `parallel_workers` or take slots out of `fleet.slots` rather than
  adding retries.

---
