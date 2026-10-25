# Ticket rules: when to file, and how big a ticket should be

Owner decision 2026-10-06, shape rules added 2026-10-22. Read by team-engineer, team-tester,
team-ticket-writer, team-pm and the fleet-planner and fleet-plane agents.
The numbers come from a measured review of one fleet week (2026-09-29 to 10-05: 224 tickets
filed, 117 shipped, 73M tokens).

## Why this exists

- The board grew by about 157 open tickets in that week, about 1.9 filed for every ticket
  shipped. Testers filed 37% of everything, and only 35% of what testers filed got closed.
  Half of everything filed was low priority.
- Most of it was the same few problems filed again and again. "A name in the wrong
  language shows in the UI" was filed 8 times. "Route admits a role its API refuses" was filed 4 times.
  Duplicate pairs were usually worked twice, not cancelled.
- Every ticket costs about 350k tokens before any code changes: worktree, slot, gate, blind
  tester. That is about 75% of a typical ticket's cost.
- A reworked ticket costs 2.45x a clean one. Rework rate: 5% under 200 changed lines, 16% at
  200 to 499, 25% at 500 and more, 42% at 21 or more files.

## 1. Before you file: the ladder

Walk it top to bottom. File a new ticket only if you reach step 5.

1. **It's small and it's in a file or screen this PR already touches** (roughly 20 lines or
   less, same feature folder).
   - Engineer: fix it in this PR and say so in the handoff.
   - Tester: don't file it. Put it in the verdict's non-blocking notes with `file:line`. The
     PM decides whether it rides along with a rework or goes into a sweep.
2. **An open ticket already covers it.** Add a comment there with the new evidence. To check,
   list the board and grep by keywords AND by the file paths involved. Search alone is not
   enough. Two testers filing the same bug cost a full cycle.
3. **It's one of the standing sweep patterns.** Add a `file:line` line to that sweep ticket's
   "Known instances". Never file a single instance on its own. Each project keeps its own
   sweeps as open tickets titled "Sweep: ...": list the board and match by title. Typical
   ones are labels in the wrong language for the active locale, a route that admits a role
   its API refuses, and raw i18n keys or error codes shown to the user. If you see a new pattern
   for the third time, propose a new sweep to the PM in your report instead of filing a
   third ticket.
4. **It's a step that runs after merge or at the main release** (a prod check, a backfill
   after promotion, "after X reaches main"). Add it to the "Release checklist" ticket with
   the exact command. A post-merge step that must run on dev right after this ticket merges
   is still its own ticket, `blocked_by` this one.
5. **File a ticket only when** it's a real user-facing defect, a money, stock or data
   integrity problem, a security problem, or a blocker. Low-priority polish with no user
   impact (naming, a guard's blind spot nobody is hitting, cosmetic spacing) does not get a
   ticket. Mention it in your handoff or verdict and stop there.

The cap stays: at most 2 new tickets per session, and the PM triages every one.

## 2. Ticket size

| | Files touched | Changed lines (adds + deletes) |
|---|---|---|
| Target | up to about 10 | up to about 500 |
| Mechanical work (table migration, deletion, rename) | up to about 20 | up to about 2000 |
| Hard ceiling, split before claiming | more than 20 | more than 2000 |

- **One ticket is one feature area**, so one engineer can hold all of it and one tester can
  check all of it in one pass.
- **Sweeps and cross-cutting changes are sliced one feature folder per ticket, at most about
  15 files each.** Wide and shallow is the worst shape we measured: two sweeps of 31 and 39
  files each took 7 or 8 sessions.
- **The floor: a change under about 150 lines does not get a ticket of its own** (raised from
  50 on 2026-10-22). Batch it with its siblings in the same area into one ticket. For example,
  all small CI and quality-gate edits ship together; so do small e2e spec fixes. The
  exceptions are anything urgent and anything that unblocks the trunk.
- **Estimate at writing time.** The ticket lists the files it expects to touch. If the list
  is past the ceiling, split it now, not after a rework.

### Shape: one outcome per ticket (owner, 2026-10-22)

The size table says how big a ticket may be. This says what goes in it.

- **A ticket delivers one thing someone can see working, end to end.** The schema, the server
  and the client for that one thing go in the same ticket. Never split by layer (1/3 schema,
  2/3 server, 3/3 client) while the whole stays under the ceiling. A layer ticket cannot be
  checked by a blind tester, and each extra ticket pays the ~350k fixed cost again. Seen
  2026-10-22: one feature (a new discount kind) was filed as three tickets, schema, server and
  client.
- **One outcome may run past the 500-line target, up to the ceiling.** The target tells you
  where to cut when there is a real choice. It never forces a layer split.
- **Siblings ship together.** Open tickets on the same component or screen with the same kind
  of fix are one ticket. Seen 2026-10-22 on one board: three open tickets each for the shared
  table component, for field errors shown in the wrong place, and for the server's reason
  hidden from the user.
- **The one-session test.** One engineer can finish it in one session and one tester can check
  it in one pass. If yes, and it is under the ceiling, it is one ticket.
- **When it must split** (over the ceiling), split by outcome: each part ships on its own and a
  tester can check it on its own. Name the parts by what they deliver, not by layer.
- **Investigation is not a ticket of its own** when the answer is likely to be a small fix.
  Put the investigation in the implementation ticket's §0 gate. File an investigation ticket
  only when the outcome is a decision or a set of new tickets.

## 3. Merge groups (PM)

- Two PRs that change the same shared component (`fleet.shared_ui_paths`) never go in the
  same merge group. The second waits for the first group's trunk run. Measured: three reverts
  on one day, each PR passed testing on its own and they broke trunk together.
- Any PR that adds or changes a browser e2e spec carries the e2e label (`ci.e2e_label`), so the
  spec runs under the full multi-worker suite before merge. One-worker local passes are not
  enough.

## 4. Review rounds by priority (owner, 2026-10-15)

How many times a ticket may go back depends on what it is, not on how many defects a reviewer
can still find. A heuristic tool always has one more edge case.

| Ticket | Rework rounds | After that |
|---|---|---|
| urgent or high, or anything touching money, stock, permissions, security or live data | as many as it takes | n/a |
| medium product work | 2, then the PM decides: ship with a follow-up ticket, or keep going | follow-up ticket for what is left |
| low priority tooling, docs, guards, catalogs, test-only | **1** | the rest becomes a non-blocking note, an "advisory" label on the tool, or one follow-up ticket |

- The PM records that call as a `PM SCOPE DECISION:` comment, so the next tester judges the
  narrower scope.
- A helper script inside a docs or catalog ticket is advisory unless the ticket says it is a
  CI gate. Measured 2026-10-14: a low-priority docs ticket took 7 sessions and about 1.2M tokens,
  mostly review rounds on its scanner, while the catalog itself was right after round 2.

## 5. PM bookkeeping

- In every resume note and final report, give **filed vs closed** for the run, counted from
  the board in the same turn.
- A low-priority ticket with no activity for 14 days gets triaged at the next preflight. It
  is folded into a sweep, batched with siblings, or closed with a reason. It does not sit
  forever.
