# PM · spawn

> Part of the PM role (`core/pm/role.md`). Read it when you spawn an engineer: slots, model, executor, logging, the standing brief. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 3) Spawn engineers — in parallel, each with a slot

One engineer session per claimed ticket, launched **together in a single message** when
picking more than one:

```
Agent(description: "engineer PROJ-134", subagent_type: "fleet-engineer", model: "sonnet",
      run_in_background: true,
      prompt: "Fleet folder: <fleet>. Work PROJ-134. Slot: A. ...")
Agent(description: "engineer PROJ-140", subagent_type: "fleet-engineer", model: "sonnet",
      run_in_background: true,
      prompt: "Fleet folder: <fleet>. Work PROJ-140. Slot: B. ...")
```

**Name every spawn `<role> <TICKET> [note]`** in its `description`: `engineer PROJ-134`,
`rework PROJ-134 round 2`, `tester PROJ-134`, `retest PROJ-134`, and `planner`, `plane`,
`merge`, `notify` or `scan` for the rest. `$L cost` reads the ticket and the role from it; a
spawn named otherwise lands under "other" and its ticket's cost comes out too low.

`<fleet>` is the absolute path of the fleet folder you resolved at the start (see the note at
the top of this file). Sub-sessions don't share your working directory, so every path in a
brief is absolute.

**Always spawn the fleet agent types** (`fleet-engineer`, `fleet-tester`), not
`general-purpose`. They carry only the tools the role uses and read the standing brief and
their role file on their own. Measured 2026-10-25 on one project: an agent's first call carries
a median 17k tokens of context against 72k for `general-purpose` (23 and 872 sessions), and every
later call carries that difference again. If the agent types are not installed (an
"agent type not found" error), fall back to `general-purpose` with
"Read <fleet>/engineering/engineer/role.md and follow it" in the prompt, and say so.

**Assign the slot yourself and write it in the brief.** Never let two sessions choose their own
ports; two independent choices can collide. Track which slot each live session holds. A slot is
free again only after its session reported teardown.

### Which model to spawn on — default by role, escalate by ticket

**You must pass an explicit `model` on every `Agent` call.** Omitting it silently inherits the
session's own model, which on this setup is `opus[1m]` — the most expensive tier, for every
worker, every verifier and every trivial rebase. That is not a decision; it is a default nobody
chose. One measured run spawned ~30 subagents, all at top tier, and hit the 5-hour usage limit
mid-run. (Their logged 185k–330k tokens each was only the size of each agent's last call; the
real spend was far larger. Measured 2026-10-25: a median engineer session processes 9.8M tokens
and a tester 14.3M, about 44 and 56 times what the log shows. `$L cost` reads the real figure.)

**Passing the model explicitly also drops the 1M-context variant, which is a separate cost
multiplier from the tier.** The `Agent` tool offers `opus` / `sonnet` / `haiku` / `fable` — there
is no `[1m]` option — so an extended-context model can *only* arrive by inheritance. Naming the
model is therefore two savings at once, and the second one costs nothing to take.

**Be careful how you justify that, though.** The `tokens` figure an `Agent` result reports is the
size of the subagent's **last call**: close to its peak context, and nothing like what it spent.
So it can show that a session stayed well inside the standard window, but it says nothing about
cost. For cost, use `$L cost`.

The honest test is behavioural, not arithmetic. Spawn on the standard variant and watch for the
symptoms of context pressure: a subagent reporting truncation or compaction, losing earlier
findings mid-run, or re-reading files it had already read. If that happens, record
`"context_pressure": true` on its row and escalate that role. Absent those symptoms, standard
context is sufficient — and one full run produced none of them.

**Defaults by role — use these unless a trigger below fires:**

| role | model | reasoning |
|---|---|---|
| tester | `opus` | Where the value is. There is no check after it besides CI/CD — a cheap tester that says APPROVED launders a bad merge straight to the client. |
| tester, copy/i18n-only ticket | `sonnet` | Owner-approved pilot from 2026-09-29. First 5 runs: 4 passes and 1 correct rework, so it stays, **for copy/i18n tickets only**: labels, translations or static text, with no logic, data or permission change. Anything else gets an Opus tester, even if it looks small. (2026-09-30: a Sonnet tester was spawned by mistake on a ticket that wasn't copy-only.) Keep logging `"pilot":"sonnet-tester"` and keep counting. |
| worker, ordinary fix | `sonnet` | Tickets here carry cited `file:line`, decided requirements and an explicit DoD — much of the reasoning is already done in the ticket. |
| worker, mechanical (rebase, re-push) | `sonnet` | **Never `haiku` for an engineer.** 2026-09-30: a Haiku engineer bypassed the pre-push hook with a false "pre-existing error" claim, and branched off a PR branch instead of trunk. The PM had to rebuild it. |
| read-only scan (triage, counting, log reading) | `haiku` | The only place Haiku goes. It never commits, pushes or writes the board. |
| ticket writer | `sonnet` | Escalate for a batch needing real design judgement. |
| planner (`fleet-planner`) | `opus` | Decides what the tickets are. A bad split costs a full ticket cycle per extra ticket. |
| Plane specialist (`fleet-board`) | `sonnet` | Files and reshapes tickets from an approved plan; the judgement is already in the plan. |

**Escalate the worker to `opus` when the ticket shows any of these** — check before spawning:

- it changes an architecture or delivery mechanism (routing, bundling, transactions, caching)
- the ticket's §0 gate asks the worker to *disprove or re-derive* something rather than confirm it
- the root cause is unknown, or the ticket cites no `file:line`
- it is concurrency, ordering, or timing
- it touches a schema/migration
- it has already been sent to Rework once — a second failure is expensive

**Never de-escalate an engineer below `sonnet`.** An engineer commits and pushes, and the cost
of one that games the gate is a rebuild plus a PM who can't trust the next green.

**Never quietly upgrade "to be safe."** If you deviate from the default, say which trigger fired
in your pick announcement. An unexplained escalation is indistinguishable from not choosing.

### Executors — Claude, Codex or opencode, picked per spawn

The table above is the **Claude** model choice. Who runs a role at all comes from the executor
registry: `core/references/executors.md` (read it once per run) and
`executors.json`. Owner defaults (2026-10-09): engineer → **codex `gpt-5.6-sol`**; an
escalation trigger above (schema, concurrency, unknown root cause, rework once, architecture,
disprove gate) → claude `opus`; tester → claude `opus` (copy/i18n-only → `sonnet`); read-only
scan → **opencode `kimi-k2.7-code`** (fallback claude `haiku`); ticket writer → claude `sonnet`.

`L=core/scripts/fleet`. Details live in executors.md; the loop is:

0. **Preflight:** `$L free-models refresh` (say the "new" and "gone" it prints), `$L cost --backfill`, then `$L cost --since <7 days ago>`: put its "per ticket"
   median lines (cost and first spawn → merge) in the opening summary. Then `$L apply`
   (promotions/demotions; say every line it prints), `$L stats --role
   engineer` and `$L status`. Put its budget line (`Claude 58% (5h) · Codex 9% (wk) · Ollama ok`)
   in the opening summary and in each status update.

   **Read the fleet with `$L status`, not piece by piece.** One call gives the budget, each
   slot and who holds it, lanes running and just ended (and any whose process died), open PRs
   with their required checks, labels and mergeability, trunk CI, and worktrees left with no
   open PR. Run it before each pick and after each notification, instead of reading the meter
   file, looping over ports, or calling `gh` per PR (measured 2026-10-25: about 2,000 such PM
   calls a month). To wait for CI, start `gh run watch <id>` with `run_in_background: true`
   and carry on; never a `sleep` loop.
1. **Tag** each spawn with role + task kind (`api`, `ui`, `schema`, `money-concurrency`,
   `copy-i18n`, `tests-only`, `infra-deps`, `retest`, `rework`) from triage paths/keywords and
   the ticket text.
2. **Pick:** `$L pick --role <role> --kind <kind> --cwd <repo> [--triggers a,b] [--urgent]
   [--attempt <rework count>]`; for the tester of an experimental engineer add `--pair-with
   <exe:model> --pair-experiment`. It returns the champion, or about 1 in 5 an experiment,
   only among executors with budget. `decision: wait` → background `sleep` until `resume_at`,
   then pick again. No registry, or the executor's binary is missing → Claude, as above.
3. **Announce** its `pick_line`: `PROJ-134 → engineer/api · codex:gpt-5.6-sol · EXPERIMENT ·
   … · slot A` (and the trigger, if one fired).
   **Spawn:** Claude via `Agent` exactly as above. Any lane executor (codex, opencode, claude-ollama): write the brief (same
   content as a Claude brief: standing-brief line, ticket, slot and its values, owned files,
   shared registries) to `/tmp/<TICKET>-<role>/brief.md`, then **Bash `run_in_background: true`**:
   ```
   $L codex --model gpt-5.6-sol --role engineer --ticket PROJ-134 --cwd <repo-root> \
     --brief /tmp/PROJ-134-engineer/brief.md --out /tmp/PROJ-134-engineer/lane
   ```
   You are notified when it exits. Read `<out>/result.json`: `lastMessage` is the report line.
   `status: deferred` (exit 75) = no budget: sleep until `resumeAt`, then pick again.
4. **A lane takes a slot** like any session and must report teardown before the slot is reused.
5. **Lane failure = dead session.** Non-zero exit, `status` not `completed`, an engineer lane
   with no PR, or a timeout: handle it like the heartbeat below (check board, branch and PR;
   clean up anything in `worktreesAdded`/`branchesAdded` that has nothing pushed), then re-queue
   the ticket **once on the role's Claude fallback**. A second lane failure on the same executor
   that day → stop using it for that role this run and say so.
6. **Log every spawn** at its end. Claude: `$L log add --ticket … --role … --kind … --executor
   claude --model … --outcome … [--experiment] --reason "…" --set duration_ms=… agent_id=…` with
   the duration and the agent id (the `task-id` of its notification) from the Agent result. Do not
   log its `tokens`: that is the last call's size, not the spend. `$L cost --backfill` writes the
   real usage onto the row from the session file, matched by `agent_id`. A tester's
   `verify_fail` needs `--cause missed|ticket|spec_changed|environment` (the table under "Read a
   low pass rate correctly"); the log refuses one without it. Lane: `$L log add --from-result <out>/result.json --kind …
   --outcome … --reason "…"` (ticket, role, executor, model, duration and tokens come from the
   file). One log for all projects, `~/.config/plane-fleet/executor-outcomes.jsonl`.
   **Back-fill** as the ticket moves: `$L log backfill --ticket … --role engineer --set
   verify_first_pass=… ci_first_pass=…`, and `reverted` / `bug_filed` when they happen. When a
   ticket reaches **Done**: `$L log add --ticket … --role pm --executor claude --model <yours>
   --outcome done --set client_visible=true|false` (true = the client can see the change).
7. The usage pacer hook gates Claude spawns; `run-lane` gates lanes with the same rules
   (`core/pm/skills/preflight.md` §0.6). A rate-limit in a lane records a back-off and is a lane failure.

### Record every spawn so the defaults can be checked later

Since 2026-10-09 every spawn goes to the one user-level log with `fleet log add` (§3
Executors, step 6), `fleet stats` computes the rates below, and `fleet report
--project <repo> --since <iso>` gives a run's totals: Done and approved tickets, sessions and
tokens by role/executor/model, tokens per Done ticket, first-pass approval, rework rounds and
the client-visible share. The old per-project file (`legacy_glob` in the executors registry)
was folded in and is still read; its row shape, for reference:

```
{"ts":"<iso8601>","ticket":"PROJ-132","role":"worker","executor":"claude","model":"sonnet",
 "escalated":false,"trigger":null,"tokens":228886,"tool_uses":60,"duration_ms":759746,
 "outcome":"pr_opened","verify_first_pass":null,"rework_count":0}
```

`executor` is `claude` / `codex` / `opencode` / `claude-ollama`; `model` is the exact id (`gpt-5.6-sol`,
`kimi-k2.7-code`). For a Claude spawn pass `duration_ms` and `tokens` with `--set` (values are
stored as numbers), and `--effort <level>` when the `Agent` call set one; `pick` returns the
candidate's effort, and a spawn logged without it is scored as the default effort. For a lane pass `--from-result <out>/result.json`: it takes `durationMs`
and the `usage` block (`input_tokens`, `cached_input_tokens`, `output_tokens`) and adds
`lane_status` when the lane did not complete. Rows written before 2026-10-09 have no
`executor`: read them as `claude`. Compute the pass rates below per **(role, executor,
model)**, and change an executor default only on the same evidence rules.

`outcome` is one of `pr_opened` / `blocked` / `verify_pass` / `verify_fail` / `done`. Fill
`verify_first_pass` on the ticket's worker row once its verify verdict is known — that is the
number that actually answers "was this model good enough".

**Read it in preflight (`core/pm/skills/preflight.md` §0) and act on it.** Compute first-pass verify rate per (role, model):

- a model whose workers pass verify first time **< ~70%** over **5+ tickets** is costing more in
  rework than it saves — raise that default and say so
- a model passing **~100%** over **10+ tickets** with no escalations is a candidate to drop a tier
- **fewer than 5 samples is not a signal.** Say "not enough data yet" rather than inventing a trend

**Read a low pass rate correctly — it is not automatically the model's fault.** The seeded
baseline is the worked example: Opus workers passed verify first time **7 of 11 (64%)**, below
the threshold, with no stronger tier to escalate to. Classify each failure before concluding
anything:

| failure cause | what it means | what to change |
|---|---|---|
| environment (budget wall, trunk moved, shared port died) | not the worker | fix the environment; exclude from the model signal |
| the ticket's own DoD was wrong or incomplete | not the worker | fix ticket quality — see the planner's `write-ticket` skill |
| the spec changed mid-build | not the worker | the text-freeze rule (`core/pm/skills/preflight.md` §0) |
| the worker missed something demonstrable it was asked to check | **this one is the model signal** | only these count toward the pass rate |

Only the last row justifies changing a model default. A pass rate dragged down by the first
three says the *tickets or the environment* need work, and moving to a bigger model will not fix
it — it will just cost more.

**And do not read this run's 64% as licence to drop a tier either.** The failures that were
genuine were failures of *thoroughness*, not of reasoning — checking the small viewport, checking
what the client would look at first. Thoroughness is the quality a cheaper model is most likely to
lose, so **pilot before switching**: run Sonnet on two or three low-risk tickets with verify still
on Opus, compare the pass rate against these rows, and only then change the default.

Report what the log says in your opening summary, even when it says nothing yet. A default nobody
re-examines is how `opus[1m]` ended up on a branch rebase.

### The standing brief — one file, referenced by EVERY spawn

Ticket-specific context is written per spawn; the boundaries are not. **Do not hand-write
them each time and do not judge which apply** — the failure mode is forgetting one, and it is a
manager error, not a worker error.

This happened: the "never change the budget value" rule was given to two workers and left out of
a third's brief. That worker hit a bundle-budget wall, raised the budget from `1mb` to `1.1mb` to
land, and the PR was green and verified. It was caught only by chance before merging — and it
would have silently re-hidden the very problem another ticket had just fixed.

The boundaries, the shared-registry rule, the filing ladder and the report rules live in
**`engineering/references/standing-brief.md`**. Put this line at the top of every
engineer and tester brief:

```
FIRST read <fleet>/engineering/references/standing-brief.md and follow it exactly; it is part of this brief.
```

Never paste the file's contents into the brief. (2026-10-08: pasting ~3 KB of boundaries into
each of ~20 spawns kept the PM's own context large, and every PM turn re-reads it. A one-line
reference costs nothing and can't drift between spawns.) Edit the file, not the briefs, when a
rule changes.

(2026-09-30, each one real: a Haiku engineer pushed with a false "pre-existing error" claim to
get past the hook; the PM gave a slot-less engineer slot A's Nx cache and it deleted the folder
while another engineer was using it; an e2e spec under the pre-push hook set `core.bare=true` in
the shared `.git/config`.)

(2026-09-30: a session started its server without API_PORT. It bound the shared row's API port, kept running
after its worktree was deleted, and held slot A's DB until a later tester found it.)

**Decide file overlap in the brief, before the spawn.** If the ticket will touch a shared
registry file another open PR also touches (i18n JSON, error codes, audit actions, DTOs,
permission matrix + contract, module providers, route table), name those files in the brief as
SHARED REGISTRIES so the standing brief's additive rule applies. Anything else another open PR
owns stays off limits. (2026-10-08: an engineer stopped before writing code because its brief listed the
permission matrix as owned by an open PR, with no ruling. ~200k
tokens, then a resume with the decision the brief should have carried.)

Then add, per spawn: the ticket id and state, **the slot letter and its values**, the PR
number/branch (testers and rework engineers), the owned-file list from currently open PRs, and
whatever is specific to that ticket.

**Get the brief right the first time. A correction sent mid-run will likely be ignored.** A
`SendMessage` to a subagent that is still working lands inside one of its tool results, where it
can't be told apart from a prompt injection. A careful subagent refuses it, and it should. (Seen
2026-09-29: an engineer declined a genuine PM correction and flagged it in its handoff.) If a brief was wrong, send the correction **after the subagent goes idle**. The resume
message then arrives as its direct instruction. Keep the correction to that session's own role.

**Triage every ticket a session files, before you pick again.** A report that names new ticket
ids is not finished until you decide each one. Judge each one against the filing ladder in
`engineering/references/ticket-rules.md` §1, and choose:
- **keep**: leave it in `Todo` at the priority the defect earns.
- **merge**: comment it into an existing ticket and set it `Cancelled` as a duplicate.
- **fold**: make it a child of its standing sweep, or move its step onto the Release checklist.
- **park**: `Backlog`, with the reason in a comment.
Say the decision in one line. Anything that changes a ticket already `In Progress` goes in a
comment, never its description. A tester's non-blocking notes are yours to place the same
way: ride along with a rework, add to a sweep, or drop with a reason.

**Check the size at pick time** (`engineering/references/ticket-rules.md` §2). Use `triage` paths and the files the ticket
lists:
- **Past the hard ceiling** (more than 20 files or 2000 lines) and not mechanical: don't
  claim it. Have the planner's `write-ticket` skill split it first.
- **Under the floor** (about 50 lines or less): batch it with its siblings into one claim
  before spawning. Exceptions are urgent tickets and anything that unblocks trunk.

Why: about 50 tickets were filed during one three-day run, more than it closed, and partial
slices each spun off more. Track `filed` against `closed` for the
run, and say both numbers when you report. A run that files faster than it closes is growing
the board, not shrinking it.

**Heartbeat, per worker.** No board write for ~30 minutes → check for a pushed branch/PR; none
→ treat as dead: comment what you found, `Todo`, remove any worktree it left, re-spawn or move
on. Never leave a ticket `In Progress` with nobody on it. A lane (§3 Executors) gets the same
check; its `<out>/started.json` and `events.jsonl` show whether it is still moving, and a lane
that exited without `completed` is dead at once, no 30-minute wait.

**A completion notification is not the same as done.** Check the board state and the actual
PR/branch, every time, before deciding what's next — same caution as ever: paused-and-resumable
(`ListAgents` still shows it) gets `SendMessage`, never a fresh `Agent` call with the id as the
prompt; dead (gone from `ListAgents`) gets ground-truth re-established from git/GitHub, then a
fresh session briefed with exactly what already exists.

---
