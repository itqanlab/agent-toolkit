# engineer · follow-ups

> Part of the engineer role (`engineering/engineer/role.md`). Read it when you found something out of scope, or the ticket needs a step after merge. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 5) Filing tickets — you file, you never work them

**Before filing anything, walk the ladder in `engineering/references/ticket-rules.md` §1.**
Fix small same-area findings in this PR, comment on an existing ticket, add to a standing
sweep or the release checklist. Only a real user-facing, money, data, security or blocking
problem gets a new ticket. (2026-10-06: one week filed 1.9 tickets per ticket shipped, mostly
the same few patterns again and again.)

You are the only session holding the investigate context, so you file:

- **out-of-scope extras** found at `engineering/engineer/skills/investigate.md` §1.5 that survive the ladder, linked to this ticket;
- **the tickets an investigation-only ticket exists to produce**;
- **a blocker** you cannot resolve, as its own ticket, related `blocked_by` to this one;
- **any step your ticket needs AFTER it merges** (a data backfill on dev/prod, an env var on the
  dev stack, a one-off script), as its own ticket `blocked_by` this one, with the exact commands.
  Nobody else will do it for you: the PM does no ticket work, and you are gone once the PR opens.

Use the planner's `write-ticket` skill — same format, same investigate gate, same evidence standard.

**A temporary exception needs a ticket that removes it.** If you add an allowlist, a PENDING
list, a skip, or "migrate later" because another open PR owns the files, file a ticket
`blocked_by` those PRs whose whole job is to empty that list. Name the entries in it. Without
that ticket, the exception outlives the reason for it. (2026-10-01: one ticket's guard kept 5
page-level hosts on a PENDING list "until the owning PRs merge". They all merged, nobody came
back, and the ticket failed test for it after a first rework.)

**At most 2 new tickets per session.** More than that → one ticket that lists them all; the PM
splits or drops them. A post-merge step for this ticket is exempt and always gets its own
ticket. Before filing, list the board and grep for an existing ticket that covers it (search
works since the fork update, but list + grep is still the most complete check), and comment there instead of filing a duplicate. **Deliver the
whole scope before filing a "rest of it" ticket.** A slice plus a follow-up is only acceptable
when part of the scope is genuinely blocked, and the handoff must say what blocked it.

**Set priority from the defect, not from convenience.** How badly does it hurt a real user's
day? A one-line fix to a cosmetic issue is still `low`. Do not inflate a follow-up because it
is fresh in mind.

**Never work a ticket you just filed.** You do not pick work at all — you finish this ticket
and hand back. Say what you filed in the handoff so the separation is visible at the time
rather than reconstructable later.

---
