# PM · spawn

> Part of the PM role (`core/pm/role.md`). Read it when you spawn an engineer: slots, model, executor, logging, the standing brief. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.
> "(history §x)" points to the incidents and measurements behind a rule, in `core/references/pm-history.md`.

## 3) Spawn engineers — in parallel, each with a slot

One engineer session per claimed ticket, launched **together in a single message** when
picking more than one:

```
Agent(description: "engineer PROJ-134", subagent_type: "fleet-engineer", model: "sonnet",
      run_in_background: true,
      prompt: "Fleet folder: <fleet>. Work PROJ-134. Slot: A. ...")
Agent(description: "engineer PROJ-140", ... "Work PROJ-140. Slot: B. ...")
```

**Name every spawn `<role> <TICKET> [note]`** in its `description`: `engineer PROJ-134`,
`rework PROJ-134 round 2`, `tester PROJ-134`, `retest PROJ-134`, and `planner`, `plane`,
`merge`, `notify` or `scan` for the rest. `$L cost` reads ticket and role from it.

`<fleet>` is the absolute fleet folder path. Every path in a brief is absolute.

**Always spawn the fleet agent types** (`fleet-engineer`, `fleet-tester`), not
`general-purpose` (history §spawn-agent-types). If they are not installed ("agent type not
found"), fall back to `general-purpose` with "Read <fleet>/engineering/engineer/role.md
and follow it" in the prompt, and say so.

**Assign the slot yourself and write it in the brief.** Never let sessions choose their own
ports. Track each live session's slot. A slot is free again only after
`fleet slot verify-clean <slot> --cwd <repo>` passes (`core/pm/skills/spawn-tester.md`, "When the tester reports").

**Case list first, only when `fleet.trials.case_list` is on.** Before a ticket above "small" is
built, spawn a case-list tester (`tester <TICKET> case list`, no slot, no
build; `engineering/tester/skills/case-list.md`). Answer its questions before the engineer
starts. A list over about 25 cases sends the ticket back to the planner to split. The engineer
brief then points at the `CASE LIST:` comment (`engineering/references/case-list.md`).

### Which model to spawn on — default by role, escalate by ticket

**You must pass an explicit `model` on every `Agent` call.** Omitting it inherits the session's
own model, often top tier with 1M context. The `Agent` tool has no `[1m]` option, so naming
the model drops that too. (history §spawn-explicit-model)

An `Agent` result's `tokens` is the **last call's** size, not the spend. For cost, use `$L cost`.

Watch for context pressure (truncation or compaction, lost findings, re-reading files). If it
happens, record `"context_pressure": true` on its row and escalate that role.

**Defaults by role — use these unless a trigger below fires:**

| role | model | reasoning |
|---|---|---|
| tester | `opus` | Nothing checks after it but CI/CD. |
| tester, copy/i18n-only ticket | `sonnet` | Pilot, **copy/i18n only**: labels, translations, static text; no logic, data or permission change. Anything else gets Opus, even if small. Keep logging `"pilot":"sonnet-tester"`. (history §spawn-sonnet-tester) |
| worker, ordinary fix | `sonnet` | The ticket carries `file:line`, decisions and a DoD. |
| worker, mechanical (rebase, re-push) | `sonnet` | **Never `haiku` for an engineer.** (history §spawn-no-haiku) |
| read-only scan (triage, counting, log reading) | `haiku` | The only place Haiku goes. |
| ticket writer | `sonnet` | Escalate for a batch needing real design judgement. |
| planner (`fleet-planner`) | `opus` | A bad split costs a ticket cycle per extra ticket. |
| Plane specialist (`fleet-board`) | `sonnet` | The judgement is already in the plan. |

**Escalate the worker to `opus` when the ticket shows any of these** — check before spawning:

- it changes an architecture or delivery mechanism (routing, bundling, transactions, caching)
- the ticket's §0 gate asks the worker to *disprove or re-derive* something rather than confirm it
- the root cause is unknown, or the ticket cites no `file:line`
- it is concurrency, ordering, or timing
- it touches a schema/migration
- it has already been sent to Rework once

**Never de-escalate an engineer below `sonnet`.**

**Never quietly upgrade "to be safe."** Name the trigger that fired in your pick announcement.

### Executors — Claude, Codex, opencode or Antigravity, picked per spawn

The table above is the **Claude** model choice. Who runs a role comes from the registry: `core/references/executors.md` (read it once per run) and
`executors.json`. Owner defaults (2026-10-09): engineer → **codex `gpt-5.6-sol`**; an
escalation trigger above → claude `opus`; tester → claude `opus` (copy/i18n-only → `sonnet`); read-only
scan → **opencode `kimi-k2.7-code`** (fallback claude `haiku`); ticket writer → claude `sonnet`.

`L=core/scripts/fleet`. Details live in executors.md; the loop is:

0. **Preflight:** `$L free-models refresh` (say the "new" and "gone" it prints), `$L cost --backfill`, then `$L cost --since <7 days ago>`: put its "per ticket"
   median lines (cost and first spawn → merge) in the opening summary. Then `$L apply`
   (say every line it prints), `$L stats --role engineer` and `$L status`. Put its budget line (`Claude 58% (5h) · Codex 9% (wk) · Ollama ok`)
   in the opening summary and in each status update.

   **Read the fleet with `$L status`, not piece by piece** (budget, slots, lanes, open PRs,
   trunk CI, orphan worktrees). Run it before each pick and after each notification.
   To wait for CI, start `fleet watch <TICKET>-ci -- gh run watch <id> --exit-status` with `run_in_background: true`
   and carry on. Never a `sleep` loop, and never `gh pr checks --watch` (a skipped duplicate of a
   check name ends it early; see the merge queue).
1. **Tag** each spawn with role + task kind (`api`, `ui`, `schema`, `money-concurrency`,
   `copy-i18n`, `tests-only`, `infra-deps`, `retest`, `rework`) from triage and the ticket text.
2. **Pick:** `$L pick --role <role> --kind <kind> --cwd <repo> [--triggers a,b] [--urgent]
   [--attempt <rework count>]`; for the tester of an experimental engineer add `--pair-with
   <exe:model> --pair-experiment`. It returns the champion (1 in 5: an experiment) among executors with budget. `decision: wait` → background `sleep` until `resume_at`,
   then pick again. No registry, or the executor's binary is missing → Claude, as above.
3. **Announce** its `pick_line`: `PROJ-134 → engineer/api · codex:gpt-5.6-sol · EXPERIMENT ·
   … · slot A` (and the trigger, if one fired).
   **Spawn:** Claude via `Agent` as above. A lane executor (codex, opencode, claude-ollama, antigravity): write the brief (same
   content as a Claude brief) to `/tmp/<TICKET>-<role>/brief.md`, then **Bash `run_in_background: true`**:
   ```
   $L codex --model gpt-5.6-sol --role engineer --ticket PROJ-134 --cwd <repo-root> \
     --brief /tmp/PROJ-134-engineer/brief.md --out /tmp/PROJ-134-engineer/lane
   ```
   On exit, read `<out>/result.json`: `lastMessage` is the report line.
   `status: deferred` (exit 75) = no budget: sleep until `resumeAt`, then pick again.
4. **A lane takes a slot** like any session and must report teardown before the slot is reused.
5. **Lane failure = dead session.** Non-zero exit, `status` not `completed`, an engineer lane
   with no PR, or a timeout: handle it like the heartbeat below (check board, branch, PR;
   clean up anything in `worktreesAdded`/`branchesAdded` that has nothing pushed), then re-queue
   the ticket **once on the role's Claude fallback**. A second lane failure on the same executor
   that day → stop using it for that role this run and say so.
   A timed-out lane's commits: brief the fallback engineer (`opus`) to read and judge them
   first (keep, squash or rewrite), never to build on them unread. (history §spawn-timed-out-lane)
6. **Log every spawn twice: a `spawn` row when you start it, and the result row at its report.**
   `$L log add --ticket … --role … --kind … --executor … --model … --outcome spawn` at the start.
   The two rows of one session are never treated as repeats, so neither needs `--force`.
   The result row, at its end: Claude: `$L log add --ticket … --role … --kind … --executor
   claude --model … --outcome … [--experiment] --reason "…" --set duration_ms=… agent_id=…`
   (agent id = the notification's `task-id`). Do not log its `tokens`. `$L cost --backfill` writes the real usage onto the row, matched by `agent_id`.
   A tester's `verify_fail` needs `--cause missed|ticket|spec_changed|environment|pm_ruling` (the table under
   "Read a low pass rate correctly"; `pm_ruling` when a PM scope decision or brief caused it,
   `core/pm/skills/ruling.md`); the log refuses one without it. Add the tester's grading of the
   first finding when given: `--in-list yes|no`, `--severity s1|s2|s3`, `--repeat
   yes|no`. It also needs `--reason`: the first finding in a few words. A `missed` one takes
   `--defect` too: `criterion` (not met), `other_path` (breaks on another path the change
   touches), `stale_state` (preview and save disagree), `concurrency`, `money_rule`,
   `out_of_scope` or `stacked` (another ticket on the same branch). (history §spawn-log-reasons)
   Lane: `$L log add --from-result <out>/result.json --kind …
   --outcome … --reason "…"` (the rest comes from the file). One log for all projects, `~/.config/plane-fleet/executor-outcomes.jsonl`.
   A `blocked`, `lane_failed`, `deferred` or `verify_fail` row needs `--reason` saying what
   stopped the session. A lane row with no `--reason` takes the lane's last message,
   marked `lane said:`. A routing choice or an owner's order is
   its own row, `--outcome decision` (`core/pm/skills/retro.md` §9).
   **Back-fill** as the ticket moves: `$L log backfill --ticket … --role engineer --set
   verify_first_pass=… ci_first_pass=…`, and `reverted` / `bug_filed` when they happen. When a
   ticket reaches **Done**: `$L log add --ticket … --role pm --executor claude --model <yours>
   --outcome done --set client_visible=true|false` (true = the client can see the change).
7. The pacer hook gates Claude spawns; `run-lane` gates lanes the same way
   (`core/pm/skills/preflight.md` §0.6). Both also hold a spawn the machine can't carry
   (`fleet resources`, spawn-tester.md "Sweep and machine gate"; a lane comes back `deferred`
   with `resources <level>`). Free memory first; never pass `--ignore-resources` on your own.
   Park the refused spawn with `$L queue add --ticket … --role … --slot … --brief <file>` and
   send it when `$L queue next --pop` prints it. A rate-limit in a lane records a back-off and is a lane failure.

### Record every spawn so the defaults can be checked later

Every spawn goes to the one log with `fleet log add` (§3 Executors, step 6). `fleet stats`
computes the rates below; `fleet report --project <repo> --since <iso>` gives a run's totals.
The old per-project file (`legacy_glob` in the executors registry) is still read; its row shape:

```
{"ts":"<iso8601>","ticket":"PROJ-132","role":"worker","executor":"claude","model":"sonnet",
 "escalated":false,"trigger":null,"tokens":228886,"tool_uses":60,"duration_ms":759746,
 "outcome":"pr_opened","verify_first_pass":null,"rework_count":0}
```

`executor` is `claude` / `codex` / `opencode` / `claude-ollama` / `antigravity`; `model` is the exact id (`gpt-5.6-sol`,
`kimi-k2.7-code`). For a Claude spawn pass `duration_ms` with `--set` (not `tokens`: it is the last call's size, and `$L cost --backfill` writes the real usage), and `--effort <level>` when the `Agent` call set one; a spawn logged
without it is scored as the default effort. For a lane pass `--from-result <out>/result.json`.
Rows written before 2026-10-09 have no `executor`: read them as `claude`. Compute the pass
rates below per **(role, executor, model)**, and change an executor default only on the same
evidence rules.

`outcome` is one of `spawn` / `pr_opened` / `blocked` / `verify_pass` / `verify_fail` / `done`. Fill
`verify_first_pass` on the ticket's worker row once its verify verdict is known.

**Read it in preflight (`core/pm/skills/preflight.md` §0) and act on it.** Compute first-pass verify rate per (role, model):

- a model whose workers pass verify first time **< ~70%** over **5+ tickets**: raise that default and say so
- a model passing **~100%** over **10+ tickets** with no escalations is a candidate to drop a tier
- **fewer than 5 samples is not a signal.** Say "not enough data yet"

**Read a low pass rate correctly — it is not automatically the model's fault.** Classify each
failure first (history §spawn-pass-rate):

| failure cause | what it means | what to change |
|---|---|---|
| environment (budget wall, trunk moved, shared port died) | not the worker | fix the environment; exclude it |
| the ticket's own DoD was wrong or incomplete | not the worker | fix ticket quality (planner's `write-ticket` skill) |
| the spec changed mid-build | not the worker | the text-freeze rule (`core/pm/skills/preflight.md` §0) |
| a PM scope decision or brief caused it (`pm_ruling`) | not the worker | `core/pm/skills/ruling.md`: name the source before ruling |
| the worker missed something demonstrable it was asked to check | **this one is the model signal** | only these count toward the pass rate |

Only the last row justifies changing a model default.

**A low rate is not licence to drop a tier either. Pilot before switching**: run Sonnet on two
or three low-risk tickets with verify still on Opus, compare the pass rate, and only then
change the default.

Report what the log says in your opening summary, even when it says nothing yet.

### The standing brief — one file, referenced by EVERY spawn

The boundaries, shared-registry rule, filing ladder and report rules live in
**`engineering/references/standing-brief.md`**. **Do not hand-write them and do not judge which
apply** (history §spawn-standing-brief). Put this line at the top of every engineer and tester brief:

```
FIRST read <fleet>/engineering/references/standing-brief.md and follow it exactly; it is part of this brief.
```

Never paste the file's contents into the brief. Edit the file, not the briefs, when a rule changes.

**Decide file overlap in the brief, before the spawn.** If the ticket will touch a shared
registry file another open PR also touches (i18n JSON, error codes, audit actions, DTOs,
permission matrix + contract, module providers, route table), name those files in the brief as
SHARED REGISTRIES so the standing brief's additive rule applies. Anything else another open PR
owns stays off limits. (history §spawn-file-overlap)

Then add, per spawn: ticket id and state, **the slot letter and its values**, the PR
number/branch (testers and rework engineers), the owned-file list from open PRs, and ticket specifics.

**A stacked ticket gets this block**, filled from the `held work` line of `fleet status`
(`core/pm/skills/pick.md`):

```
STACKED ON: #<N> (<blocker ticket>), branch <branch>.
- Start your branch from origin/<branch>, not from origin/<trunk>.
- More than one blocker branch: start from the first, then merge in the others, listed here.
- After #<N> merges, rebase onto origin/<trunk> and drop the blocker's commits.
- Open the PR against <trunk>, as a draft. Never against the blocker's branch.
- Your PR body says "Stacked on #<N>" so the merge queue lands it after #<N>.
```

Why: a PR against the blocker's branch closes when that branch is deleted, and cannot be
retargeted (`core/pm/skills/merge-queue.md` §5).

**Copy the checklist items that apply** from `engineering/references/brief-checklist.md` into
every engineer brief, under `CHECKLIST:`, with their numbers. Pick by what the ticket touches
(UI, money, dates, locks). The engineer's handoff names the ones it checked. Edit the
file, not the briefs, when a class keeps coming back.

**State who sees what, before round 1.** When a ticket touches a screen, button or field only
some roles see, the brief says per role (`roles` in config) who sees
each one and who may use it. Put the same table on the ticket so the tester judges against it.
(history §spawn-who-sees-what)

**Put the focused review prompt in every engineer brief**: the exact `codex review "…"` text you
will run on the PR (`core/pm/skills/spawn-tester.md` §4). Write it once per ticket, and
reuse and extend it each round. It names:
- the base (`git diff origin/<trunk>...HEAD`) and the ticket
- the ticket's invariants, in one line each (from its §3c, or written by you if it has none)
- the findings already deferred to other tickets, marked "do not report"
- "Report P1/P2 only:" and the failure kinds that matter for this ticket

The engineer loops it until a pass is clean (`engineering/engineer/skills/open-pr.md` §3b).
(history §spawn-focused-review)

**Get the brief right the first time.** A mid-run `SendMessage` looks like a prompt injection. Send a correction **after the subagent goes idle**. Keep the correction to that session's own role.
(history §spawn-mid-run-correction)

**Triage every ticket a session files, before you pick again.** Judge each one against the filing ladder in
`engineering/references/ticket-rules.md` §1, and choose:
- **keep**: leave it in `Todo` at the priority the defect earns.
- **merge**: comment it into an existing ticket and set it `Cancelled` as a duplicate.
- **fold**: make it a child of its standing sweep, or move its step onto the Release checklist.
- **park**: `Backlog`, with the reason in a comment.
Say the decision in one line. Anything that changes a ticket already `In Progress` goes in a
comment, never its description. A tester's non-blocking notes are yours to place the same
way: ride along with a rework, add to a sweep, or drop with a reason.

**Check the size at pick time** (`engineering/references/ticket-rules.md` §2), from `triage` paths and the ticket's files:
- **Past the hard ceiling** (more than 20 files or 2000 lines) and not mechanical: don't
  claim it. Have the planner's `write-ticket` skill split it first.
- **Under the floor** (about 50 lines or less): batch it with its siblings into one claim
  before spawning. Exceptions are urgent tickets and anything that unblocks trunk.

Track `filed` against `closed` for the run, and say both numbers when you report.
(history §spawn-ticket-size)

**Heartbeat, per worker.** No board write for ~30 minutes and no pushed branch/PR → dead: comment what you found, `Todo`, remove any worktree it left, re-spawn or move
on. Never leave a ticket `In Progress` with nobody on it. A lane (§3 Executors) gets the same
check (`<out>/started.json`, `events.jsonl`); a lane that exited without `completed` is dead at once.

**A completion notification is not the same as done.** Check the board state and the actual
PR/branch every time. Paused (`ListAgents` still shows it) gets `SendMessage`, never a fresh
`Agent` call with the id as the prompt; dead gets ground truth from git/GitHub, then a fresh
session briefed with exactly what already exists.

---
