# engineer · investigate

> Part of the engineer role (`engineering/engineer/role.md`). Read it when you start: the investigate gate, before the first line of code. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 1) Investigate gate — mandatory, before the first line of code

Every ticket is a **hypothesis**, not an instruction. Tickets go stale between filing and
execution; this board has burned that way before.

0. **Record the ticket's `updated_at` before you read anything else**, and carry it to your
   handoff comment (`engineering/engineer/role.md` §6) as `built against ticket updated_at <timestamp>`. A ticket can be
   rewritten *while you build against it* — by the client, a project manager, or another agent
   session on the same board. This is real: one ticket's description reversed from "do NOT
   include a `shared/` folder" to requiring one, after its PR was already open and green. That
   line is how the tester tells "did not meet the spec" apart from "the spec changed
   underneath", so without it your correct work can be failed for a requirement that did not
   exist when you built it.

1. **Re-verify every claim** at its cited `file:line`. Stale → say so in a ticket comment and
   adjust. Never implement against a false premise; never silently drop the item.

   Two claim-discipline rules, because a wrong claim here becomes a wrong build:

   - **Never assert a negative from one search shape.** "Nothing calls this", "no path does
     X", "this is dead code" are the claims that get acted on hardest, so they need the most
     evidence. Either enumerate across every shape (repository query, in-memory `.find()`, raw
     SQL, dynamic dispatch), or write the weaker true sentence: "I found no X *by searching for
     Y*".
   - **Before contradicting shipped work, read that work's own ticket and migration notes.**
     Cite what you found; if the old reasoning still holds in part, keep that part.

2. **Reproduce it** in the running app **as the role that actually hits it**, in your slot
   (`engineering/engineer/skills/open-pr.md` §4.2 has the bring-up). Reproducing on trunk first gives you the "before" you compare against
   in your own browser review.

3. **Hunt the gap the ticket missed** — enumerate the full surface, not the slice the ticket
   names: every call site, every input, every route, every role. That enumeration is the real
   fix list. For a **sweep-scoped** ticket ("every X in the app"), the ticket should already
   carry the enumerated list (per the current the planner's `write-ticket` skill rules) — re-verify that list is
   still exhaustive against current code rather than re-discovering it from nothing; if you
   find an instance the list missed, add it and say so in your findings comment.

4. **Flag a migration now, before you branch.** If implementing this ticket needs a schema
   change (a file in `fleet.schema_paths`) and the PM did not already mark this ticket as the
   migration ticket, **stop here and post a comment saying so before creating your worktree.**
   Your slot DB and your worktree's generated client are yours, so running the migration is not
   the problem.
   Two migrations authored in parallel collide in `migrations/` and in ordering on trunk, and
   the PM runs only one schema ticket at a time for that reason. If it did mark you as
   the migration ticket, carry on and author it, following the repo's own migration notes
   (`fleet.schema_notes` in config, or the repo's contributor docs).

5. **Post findings as a Plane comment before the first commit** — confirmed / stale / extra.
   In-scope extras fold into this PR. So does a small fix of the same kind in a file or screen
   you already touch (about 20 lines, same feature folder): fixing it now costs a few minutes,
   and a ticket of its own costs a median $2.9 even under 50 lines (measured 2026-10-25). Out-of-scope extras go through
   the filing ladder (`engineering/engineer/skills/follow-ups.md` §5).

   **Ticket scope already locked** (author marked "do not re-open", or a sibling ticket
   already carries the investigate findings) → post one line saying why instead of the full
   findings comment. Zero comments on a ticket is indistinguishable from a missed gate later.

If the ticket is **investigation-only** (no code expected), the deliverable IS the findings
comment plus the tickets it spawns (`engineering/engineer/role.md` §6). Then go to `engineering/engineer/role.md` §7 and hand back — there is no PR, and no
worktree is needed.

---
