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
- the report says `needs PM scope call` → read the P1 and the engineer's scope argument in its
  ticket comment, and decide in a `PM SCOPE DECISION:` comment: fix it in this PR (back to the
  engineer), or file it as a follow-up with a reason. No tester until you have decided.
- a P2 marked "not applicable" with a reason you disagree with → post a `PM SCOPE DECISION:`
  saying it must be fixed, and send it back.
- the handoff shows no pass count for the brief's focused prompt, or a P2 left open without
  your sign-off → back to the engineer. No tester yet.
- otherwise, spawn the tester.

**Run the focused review yourself, while the tester works.** On every PR of kind
`money-concurrency`, `schema` or `api`, and on any ticket touching privacy, auth or audit: check out
the pushed branch in a review worktree (`.claude/worktrees/pm-review-<pr>`, `git checkout
--detach origin/<branch>`) and run the brief's focused prompt in the background, with its
output going to a file: `codex review "…" > <tmp>/<TICKET>-pm-review.md 2>&1`. It takes about 5
minutes and needs no slot. **Read it only through `fleet findings <tmp>/<TICKET>-pm-review.md`**:
one count line and the findings, deduplicated. Never `cat`, `tail` or Read the file itself; it
holds every file the reviewer read. Exit 4 means the review did not finish (an error or a usage
limit): run it again or on another executor, it is not a clean pass.
- A finding → send it to the running tester at once: reproduce it, write the failing test,
  and put it in the same verdict. Don't send the engineer a second Rework later for it.
- Wait for both the tester's verdict and your review before you route a Rework, so the engineer
  gets every known finding in one round.
- **An APPROVED on these kinds does not count until your review is back clean.** Don't queue it
  for a group while the review is still running. A tester approval followed by a reviewer P1 at
  group time costs a dropped branch, a rebuild and a full extra round.
- Run it on a different executor from the engineer's. Two passes by the same model miss the
  same things.
- **Read the engineer's own open notes first.** Its handoff often lists "minor" or P3 notes.
  On these kinds, any note that touches totals, balances, permissions or data written is a
  must-fix before the tester starts, not a later follow-up.
(2026-10-30, one project: a price-confirm ticket took four test rounds. The tester approved
round 1, the group review then found a P1, and that P1 and the next two were all in the
engineer's own round-1 notes.)
(2026-10-27/28, one project: this review found a P1 or P2 the tester's blind pass had not
reached on 993, 1006, 1011 and 1035, among them a double refund, a commit with no carrier
request, and customer data in the logs.)

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
  - **Every rework brief asks for the class, not the case.** Name the failure, then say: find
    every path, call site, state and entry point with the same shape, fix them all, and list
    each one checked in the handoff. The retest brief hands that list to the tester to try.
  - **Switch executor after one miss.** If a rework comes back and the same class fails again,
    the next round goes to a different, stronger executor. Don't give the same lane a third try.
  - **Cap at two reworks, and treat hitting it as a fleet defect.** A third failure means one of
    our steps let it through: the ticket, the build, the test, the review or the PM's own briefs.
    Before anything else:
    1. Find the step. Read the ticket against the findings: was each finding in the ticket, or
       added later? Compare the rework brief with the retest brief: did they name the same cases?
       Check which executors built and tested each round.
    2. Write it in the rework ledger: the step, what it missed, and the change to its template,
       brief or rule so it can't happen the same way again. Apply changes inside the PM routine
       at once. Propose the rest to the owner. `fleet retro` names these tickets too
       (`rework_rounds`, `ticket_cause_failures`); its findings go in the same ledger
       (`core/pm/skills/retro.md`).
    3. Put round 3 to the owner with that cause: redesign, ship with a follow-up ticket, or drop
       it. Don't start round 3 on your own. When it goes ahead, it fixes the design, not one more
       guard (for example, one check computed from everything the result depends on, instead of
       a check per case), and it runs on a different, stronger executor.
  - **A tester finding outside the ticket is a scope decision, not a Rework.** If the ticket
    never asked for the behaviour, decide it yourself in a `PM SCOPE DECISION:` comment: add it
    to this ticket with a written rule for the whole class, or file a follow-up. Never send it
    back as one case to fix.
  - **The rework brief and the retest brief use the same written list of cases.** Write the
    list once, on the ticket, and point both briefs at it.
  (2026-10-30, one project: three tickets went 2 to 4 rounds. Each round fixed only the one call
  site or state the tester named, and one lane missed the same class three times.)
- The tester stopped because the ticket text changed after the build → scope is your call.
  Decide, comment the decision on the ticket, then either re-test or send to Rework.

**Sweep and machine gate, before every spawn and after every report.** Run
`engineering/scripts/fleet-sweep.sh --repo <repo> --live <slots in use, e.g. A,C,F>`. It lists what dead
or finished sessions left running (servers on slot ports of slots not in use, processes in
removed worktrees or other slots' scratch dirs, Nx daemons, headless Chromium older than 3
hours or tied to a free slot), lists other projects' servers under "not ours" (never touched;
tell the owner once), and prints the machine gate from `fleet resources`.
- Leftovers → rerun with `--kill`, and say in one line what was stopped. Duplicate waits (the
  same `until`/`while` loop running more than once) are leftovers too; the newest copy is kept.
- **The machine gate** (`fleet resources`, also the `machine:` line of `fleet status`) measures
  memory the OS can still hand out, swap against RAM, load per core (CPU busy on Windows) and
  free disk, on macOS, Linux or Windows, against limits scaled to this machine (config
  `fleet.resources`). It names the biggest processes, says whose they are (`fleet` = inside a
  worktree) and what is safe to do about each. On macOS swap in use counts as tight at most:
  macOS grows swap files on demand and keeps old pages from apps open for days, so the kernel's
  memory-pressure level and the swap-out rate decide instead. (2026-10-31: a "swap nearly full"
  rule held every spawn for 3 hours while RAM was 58% free and nothing was paging out.) Levels:
  - **ok** → spawn as the slot rules allow, up to "room for N heavy".
  - **tight** → a heavy spawn (engineer or tester with a server, Jest or a browser) only while
    "room for N heavy" is at least 1; light work (scans, plans, reviews with no server) goes on.
  - **closed** → spawn nothing heavy, not even a tester. Let running sessions finish; re-check
    after each report.
  - **critical** → spawn nothing, and free memory now, in this order: sweep `--kill`; run every
    fix marked "(safe)" on a machine hog (they free memory without losing anyone's work, for
    example `watchman shutdown-server`); then tell the owner in one message what is still big and
    whose call it is (browsers, a VM's memory limit). If it is still critical after that, stop
    the newest heavy session's test run or server (not its worktree) and say so.
  - `run-lane` and the usage-pacer hook enforce the same gate: a lane is `deferred` and a Claude
    spawn is held. Don't route around it; the owner can switch it off with
    `~/.config/plane-fleet/resources-off`.
  - **Read the whole machine, not only the fleet.** The worst hog is often not a fleet session.
    (2026-10-29: load 72 and 900 MB of swap left on a 32 GB Mac. watchman, the file watcher
    Jest uses, held 11 GB because its watch on the repo root covered every worktree's
    node_modules; lane churn made it re-crawl the tree 5,863 times. The old gate read one macOS
    number and was prose the PM skipped: four sessions were spawned at load 26 on 12 cores.)
  - **Keep watchers off the worktrees.** A `warning:` line means a file watcher (watchman,
    an indexer) is rooted over the worktree folder. Drop that watch now (`watchman watch-del
    <root>`). To stop it coming back, turn watchman off for Jest (`watchman: false` in the Jest
    config; briefs already pass `--no-watchman`) or keep worktrees outside the repo; that is a
    ticket for the repo, not a PM edit. **Never add the worktrees to `ignore_dirs` in a repo-root
    `.watchmanconfig`.** watchman then treats the repo root as the project for every worktree,
    ignores the worktrees, and Jest finds no tests: a pre-push hook passed green with three
    failing tests that way (2026-10-29).
- Size the fleet to the machine, not to the slot list: "room for N heavy" already counts what
  is running. A small laptop may run one heavy session; that is the gate working.
- **Put the load rules in every brief:** Jest at `--maxWorkers=2 --no-watchman`, server e2e at the worker
  count its config sets, and `<fleet> resources --wait` (give the full path of the fleet
  command) before starting Jest, Playwright or a server. It returns when the gate opens or
  after 4 minutes; a nonzero exit means wait again or report. No `uptime` arithmetic in
  briefs: core counts and OS differ. A pre-push hook runs its own
  Jest workers, so two sessions pushing at once is the usual spike.
  (2026-10-27/28: four heavy lanes plus two pre-push hooks drove a 12-core Mac to a load of 108.
  A group-fix engineer's local runs timed out and crashed at loads of 36 to 61, which cost hours.)
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
