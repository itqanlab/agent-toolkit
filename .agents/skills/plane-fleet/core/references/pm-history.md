# PM history

The incidents, measurements and long reasons behind the rules in `core/pm/skills/preflight.md`
and `core/pm/skills/spawn.md`. The rules themselves live in those files. Nothing here is a rule:
read it when you want to know why a rule exists, or before you change one.

## preflight.md §0

### preflight-autocompact

Every PM call re-reads the whole context, so context size is what the PM costs. The PM's
context grows about 1.3k tokens a call: a median 177k early in a session and 650k by call 400.
Calls over 400k were 48% of PM spend (measured 2026-10-25). The default window on a 1M model
compacts near 967k.

2026-11-01, one project: with a 300k window the PM averaged 224k of context per call over 873
calls and spent $68, more than all agents together at $62.

### preflight-guard

2026-11-08, one project: 3.4 hours lost to a sleeping machine and 2 to an expired login in one
27 hour run, and neither was visible from the board. Lost time shows in `fleet retro`.

The guard checks every 20 minutes that an agent call still works, and alerts on two failed
checks in a row and again on recovery.

### preflight-hogs

A file watcher rooted at the repo (watchman, an indexer) covers every worktree. Known hogs (a
VM, a leftover Nx daemon, old headless browsers) take what the slots need.

### preflight-big-outputs

2026-11-01: the PM read a whole 283 KB review transcript to get two findings, and every later
call carried it.

### preflight-board

The fork filters and sorts inside the MCP and returns compact rows, so the JSON that reaches the
PM is only the rows it asked for. `list` comes back in priority order, newest ticket first
within a priority; `per_page` caps the rows after sorting.

`fields` turns a 6,941-byte row into 280. Pulling the whole board once overflowed the
tool-result limit; `workitem count` answers the same question in a couple of hundred bytes.

The update reply carries `state_name` and `description_escaped`. The comment reply is `{id,
workitem, created_at, comment_chars, comment_escaped}`, not the comment echoed back.

This Plane edition refuses `pql`, which is why the fork filters inside the MCP. A filter on a
field the fetch did not carry fails every row and looks like a real empty answer. `count`,
`search` and relation listing all work now; much of the older advice was about 0.2.9.

### preflight-resume-note

The FLEET RESUME NOTE says in one read what merged, what is owed, which PRs are unverified,
which decisions the user made that are not in any ticket description, and which environment
facts not to rediscover. Notes go stale: the run that wrote one may have kept working afterwards.

### preflight-peers

In one run, six tickets appeared that the PM had not filed, and an in-flight ticket's
description reversed mid-build. Both came from a peer session working the same board. A peer
session can file tickets, rewrite descriptions and edit the same files with no visibility to
the PM.

The worker's `built against ticket updated_at` line and the tester's Phase A check exist to
catch a ticket's text changing under a worker. A rebase conflict you did not predict is a
symptom of files moving under an open PR, not a mystery.

### preflight-scope-decision

2026-09-30: a tester failed correct work because the owner's later decision lived only in an
ordinary comment, and another because a criterion the owner had put out of scope was still in
the description. Two sessions rewriting the same spec is how correct work gets failed for a
requirement that did not exist when it was built.

### preflight-backlog

A fleet run that notices Backlog, logs a line about it, and then declares the queue "empty"
once Todo and Rework run dry has silently taken over the parking decision. The failure this
census guards against is never asking, not the existence of a Backlog.

A 9-ticket chain sat parked 16 days because its two parent tickets never closed and their first
real children were `blocked_by` them. Undecided tickets filed into `Todo` get worked and
closed; filed into `Backlog` they wait forever. That is the same dead end as a stranded chain,
caused by filing location instead of a relation.

Stale low-priority census: half of a week's filings were low priority, and nothing was working
through them.

### preflight-budget

No agent tool queries the provider's rate-limit meter directly. A mode computed once at
preflight is already stale a few spawns in, and that staleness is what causes a mid-flight
cutoff.

After the user mentions the limit, the PM cannot see the meter, so "I can afford one more slot"
is a guess. A wrong guess costs the slot and leaves the session it funded half-done. Asking
costs seconds. Merging and board writes are nearly free in CONSERVE, and landing a verified PR
is finishing work, not starting it.

### preflight-pacer

2026-10-08: the PM handed back at a pace-based 46% hold and the fleet idled 19:50 to 03:53.
The same day a 61% read of the status file was really 99%: that file can be stale or missing
the `five_hour` block. The pacer log lets the cost of one spawn in % be measured over time.

### preflight-pause

The 2026-09-29 to 10-01 run hit the 5-hour limit 3 times. Once it sat idle from 04:00 to 12:40
because the PM told the owner to restart it instead of arranging to continue.

### preflight-fresh-pm

Owner, 2026-10-01: a small context is only safe if every decision comes from a fresh lookup,
and a long run erodes that, since old tool output crowds out the current state. A resume note
that is complete on its own makes a restart safe whether it comes from the owner, automatic
compaction or a usage-limit pause.

2026-10-08: the PM told the owner "a fresh PM would run cleaner" and stopped; 8 idle hours.
Owner: "does not make sense to wait for the human".

## spawn.md §3

### spawn-agent-types

Measured 2026-10-25 on one project: an agent's first call carries a median 17k tokens of
context against 72k for `general-purpose` (23 and 872 sessions), and every later call carries
that difference again. The fleet types carry only the tools the role uses and read the standing
brief and their role file on their own.

### spawn-slots

Two independent port choices can collide, which is why the PM assigns every slot.

### spawn-explicit-model

Omitting `model` inherits the session's own model, which on one setup was `opus[1m]`: the most
expensive tier, for every worker, verifier and trivial rebase. That is a default nobody chose.
One measured run spawned about 30 subagents, all at top tier, and hit the 5-hour limit mid-run.
Their logged 185k to 330k tokens each was only the size of each agent's last call. Measured
2026-10-25: a median engineer session processes 9.8M tokens and a tester 14.3M, about 44 and 56
times what the log shows.

The 1M-context variant is a separate cost multiplier from the tier. The `Agent` tool offers
`opus` / `sonnet` / `haiku` / `fable` with no `[1m]` option, so an extended-context model can
only arrive by inheritance. Naming the model saves both.

The `tokens` figure in an `Agent` result is close to the subagent's peak context. It can show a
session stayed inside the standard window, but says nothing about cost. The honest test for
context size is behavioural: one full run on standard context showed no pressure symptoms.

A default nobody re-examines is how `opus[1m]` ended up on a branch rebase.

### spawn-sonnet-tester

The Sonnet tester for copy/i18n tickets was an owner-approved pilot from 2026-09-29. First 5
runs: 4 passes and 1 correct rework, so it stayed. 2026-09-30: a Sonnet tester was spawned by
mistake on a ticket that wasn't copy-only.

The Opus tester is where the value is: a cheap tester that says APPROVED launders a bad merge
straight to the client. Ordinary fix tickets carry cited `file:line`, decided requirements and
an explicit DoD, so much of the reasoning is already done. The planner decides what the tickets
are. The Plane specialist files from an approved plan. A scan never commits, pushes or writes
the board.

### spawn-no-haiku

2026-09-30: a Haiku engineer bypassed the pre-push hook with a false "pre-existing error"
claim, and branched off a PR branch instead of trunk. The PM had to rebuild it. An engineer
commits and pushes, and one that games the gate costs a rebuild plus a PM who can't trust the
next green. An unexplained escalation is indistinguishable from not choosing.

### spawn-status

Reading the fleet piece by piece (the meter file, a loop over ports, `gh` per PR) was about
2,000 PM calls a month (measured 2026-10-25). `$L status` gives the budget, each slot and who
holds it, lanes running and just ended (and any whose process died), open PRs with their
required checks, labels and mergeability, trunk CI, and worktrees left with no open PR.
`fleet watch` has no expiry, so it outlasts a long CI run.

### spawn-timed-out-lane

2026-10-27: a Codex lane timed out at 2 hours with 13 unpushed commits going in circles; an
Opus engineer replaced them with one fix. A timed-out lane that left commits is not a head start.

### spawn-log-reasons

2026-11-16: 67 of 186 failures had no reason, so the review could not say which kind of rework
to cut. The same run had 12 of 21 blocked sessions with no reason, so the review could not tell
a ticket gap from a stuck lane. The log now refuses a `verify_fail` without `--cause`, and a
`blocked`, `lane_failed`, `deferred` or `verify_fail` row without `--reason`.

The `tokens` of a Claude result is the last call's size, not the spend; `$L cost --backfill`
writes the real usage from the session file. A lane row takes ticket, role, executor, model,
duration and tokens from `result.json` (`durationMs` and the `usage` block: `input_tokens`,
`cached_input_tokens`, `output_tokens`), and adds `lane_status` when the lane did not complete.

Defect kinds in full: `criterion` (a criterion not met), `other_path` (works on one path, breaks
on another the change touches), `stale_state` (preview and save disagree), `concurrency`,
`money_rule` (rounding or a money rule applied differently), `out_of_scope` (the ticket never
asked for it), `stacked` (another ticket on the same branch).

### spawn-record

Since 2026-10-09 every spawn goes to the one user-level log. `fleet report` gives Done and
approved tickets, sessions and tokens by role, executor and model, tokens per Done ticket,
first-pass approval, rework rounds and the client-visible share. The old per-project file was
folded in. `pick` returns the candidate's effort. `verify_first_pass` is the number that
answers "was this model good enough". A model under ~70% first pass over 5+ tickets costs more
in rework than it saves.

### spawn-pass-rate

The seeded baseline: Opus workers passed verify first time 7 of 11 (64%), below the threshold,
with no stronger tier to escalate to. A pass rate dragged down by environment, ticket, spec or
PM causes says the tickets, the PM or the environment need work. A bigger model will not fix
it; it will only cost more.

Do not read that 64% as licence to drop a tier either. The genuine failures were failures of
thoroughness, not reasoning: checking the small viewport, checking what the client would look
at first. Thoroughness is what a cheaper model is most likely to lose, hence the pilot.

### spawn-standing-brief

The failure mode of hand-written boundaries is forgetting one, and that is a PM error, not a
worker error. The "never change the budget value" rule was given to two workers and left out of
a third's brief. That worker hit a bundle-budget wall, raised the budget from `1mb` to `1.1mb`
to land, and the PR was green and verified. It was caught only by chance before merging, and it
would have re-hidden the problem another ticket had just fixed.

2026-10-08: pasting about 3 KB of boundaries into each of about 20 spawns kept the PM's own
context large, and every PM turn re-reads it. A one-line reference costs nothing and can't
drift between spawns.

2026-09-30, each one real: a Haiku engineer pushed with a false "pre-existing error" claim to
get past the hook; the PM gave a slot-less engineer slot A's Nx cache and it deleted the folder
while another engineer was using it; an e2e spec under the pre-push hook set `core.bare=true` in
the shared `.git/config`.

2026-09-30: a session started its server without API_PORT. It bound the shared row's API port,
kept running after its worktree was deleted, and held slot A's DB until a later tester found it.

### spawn-file-overlap

2026-10-08: an engineer stopped before writing code because its brief listed the permission
matrix as owned by an open PR, with no ruling. About 200k tokens, then a resume with the
decision the brief should have carried.

### spawn-who-sees-what

2026-11-04, one project: several tickets went back because the tester judged visibility one way
and the engineer the other, and the ticket said neither.

### spawn-focused-review

When the PM's review is a stricter test than the engineer's, the engineer hands over a PR the PM
then sends back. 2026-10-28: the generic review called four PRs clean in a row. The PM's
focused prompt then found a P1 or P2 on each of them.

### spawn-mid-run-correction

A `SendMessage` to a subagent that is still working lands inside one of its tool results, where
it can't be told apart from a prompt injection. A careful subagent refuses it, and it should.
Seen 2026-09-29: an engineer declined a genuine PM correction and flagged it in its handoff.
Sent after the subagent goes idle, the resume message arrives as its direct instruction.

### spawn-ticket-size

About 50 tickets were filed during one three-day run, more than it closed, and partial slices
each spun off more. A run that files faster than it closes is growing the board, not shrinking
it. A report that names new ticket ids is not finished until each one is decided.
