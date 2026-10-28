# PM · pick

> Part of the PM role (`core/pm/role.md`). Read it when slots are free: drain first, triage, pick and claim, new work through the planner. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 2) Pick and claim — up to N at once

### First: is the queue test-bound or merge-bound? Drain before you pick.

**Before spawning an engineer, check what is already in flight.** Starting new tickets while
finished work piles up makes the run slower, not faster.

- **Test-bound:** more tickets in `In Review` than free slots can take, or `Todo`
  is mostly blocked by files open PRs own. → Give free slots to **testers first**. A tested,
  landed PR frees its files and unblocks several tickets; another engineer does not.
- **Merge-bound:** `Approved` PRs waiting on CI or on trunk. → Run the merge queue (`core/pm/skills/merge-queue.md` §5) before
  picking. Merging costs you almost nothing and frees files.

Say which one you are in when it happens ("3 PRs waiting for test, giving slot B to a tester").

**Cap PUSHES, not starts.** Keep engineer slots busy even while the merge queue is long. An engineer
builds and tests locally for 20–30 minutes before it pushes anything, so starting it adds no CI
load, and by the time it opens a PR a train has usually landed. The cap applies to *open PRs*:
with 6 or more open PRs from this run (`In Review`, `Testing`, `Approved`, `Rework` with a PR),
engineers already open every PR as a **draft** (the engineer role, since 2026-09-30), and every PR stays
a draft through approval. Only the group PR is marked ready, so the heavy CI runs once per group plus
once on trunk. **Never `gh pr ready` a single ticket's PR, not even to get its e2e run** (owner,
2026-10-16: three single PRs marked ready that day each ran the full CI twice). Never leave slots idle only because the merge
queue is long. (2026-09-30: a "no engineer at ≥4 open PRs" rule left every slot idle for an hour
while CI drained, and the owner asked why nothing was running.) Measured 2026-09-29/30: 9 open
PRs put 18+ jobs in the runner queue, so the pushes are what need limiting, not the work.

**One slot pool, no idle slots.** Engineers and testers draw from the same `fleet.slots`. Engineers
are capped at `fleet.parallel_workers`; testers are capped only by free slots. Whenever a slot is
free and a PR is in `In Review`, a tester takes it at once. Measured 2026-09-29: with a fixed
`parallel_testers: 1`, a PR sat 19 minutes in `In Review` while two slots were idle and no
engineer work was left to start.

**Slot priority when slots are scarce:** tester for the oldest `In Review` PR → rework engineer →
fresh engineer.

`workitem(action="list")` for `Todo`, plus anything in `Rework`.

**Drop what is not workable** (specs/parent docs with children, blocked tickets — read
relations via `workitem_relation(action="list")`; an unparsed error means treat as blocked, never as
unblocked; tickets filed during this run wait their turn except an `urgent` regression on a
batch you just shipped).

**Check at pick time whether a ticket can finish without the owner.** Skip it, or put the
question to the owner BEFORE claiming, if any of these apply:
- the done criteria include a step only the owner may approve (a prod data change, a prod env
  change, a payment or client-facing send the owner reserves)
- it builds a credential or security bypass (a token-minting, PIN-bypass or auth-skip path).
  Agents may refuse or get blocked partway through writing it up.
- it's `[Decision needed]` or investigation-only (no PR to carry through the flow)

### Pre-pick triage: a script, not an engineer, finds stale tickets and open questions

Before claiming, run the scan on every candidate you're about to pick. It is two steps and costs
a few seconds. First the Plane side, one MCP call for up to 25 tickets:

```text
workitem(action="triage", workitem_identifiers=["PROJ-373","PROJ-412"],
         path_prefixes=["apps","libs"], comments=true)
```

Each row carries `paths`, `vague_scope`, `decision_words`, `decision_comments` and
`comments_after_update`. Then the repo side, per ticket, with the `paths` triage returned:

```bash
engineering/scripts/repo-scan.sh PROJ-373 develop apps/... libs/...
```

It prints one line: `trunk-commits:` (commits on `origin/<trunk>` whose subject names the
ticket), `prs:` (PRs whose title or branch names it exactly) and `missing-paths:` (cited paths
gone from the trunk). It makes no Plane call.

Each hit is a **candidate**, not a verdict:

| Hit | What it suggests | Do |
|---|---|---|
| `trunk-commits:N>0` or a `MERGED` PR | work already landed | read the commit subject. Clearly the same fix → comment the evidence, close the ticket yourself (`Done` if shipped, `Cancelled` if superseded), no engineer. Unclear → spawn the engineer and name the commit in the brief. |
| an `OPEN` PR you didn't spawn | someone else is on it | don't claim. Tell the owner. |
| `missing-paths:` | the cited code moved or was deleted | the ticket's §0 gate starts from "find where this lives now". Say so in the brief. |
| `vague_scope` not empty | "everywhere", "all screens", "the whole app" with no list | **don't claim it yet.** Spawn the planner (`fleet-planner`) to write it with its `write-ticket` skill (sonnet) to replace each vague word with the enumerated list (`file:line` each) in the description, then pick it. An engineer building against "everywhere" is the most reliable way to get a Rework (393 failed twice). |
| `decision_words` not empty | the ticket asks a question | read the body. A real open question goes to the owner **before** claiming. |
| `decision_comments` > 0 | a decision may live in a comment, not the description | read those comments. If a decision changed the scope, **write it into the description now, before claiming.** The text-freeze rule (`core/pm/skills/preflight.md` §0) only starts at claim. |

Why: in one three-day run, 13 tickets turned out stale or duplicate only after a full engineer
session each, about 2.5M tokens in total. Another 6 burned a session before a question for the
owner surfaced. And one was failed by its tester because the owner's later decision lived only
in a comment.

If the owner's answer leaves the ticket unable to finish, **pick a different ticket for that
slot**. (Seen 2026-09-29: both picks of a 2-ticket run stalled. One ticket's production half was held
by the owner, and the other's engineer stopped before the PR after a safety check blocked its
write-up twice. The run delivered nothing end to end until replacements were picked.)

**Order by: OLDEST TICKET FIRST (owner, 2026-10-03).** Pick by lowest sequence id (creation
order), across every priority, `low` and `none` included. Priority does not jump the queue. Get
the list with `order_by="sequence_id"` (ascending), never the default sort, which is priority
first and newest first within it.

Why: every run files follow-ups, and the client adds tickets too. Under priority-first, the
fresh `high` follow-up always wins and the old ticket waits forever, then goes stale or gets
contradicted by newer tickets nobody linked to it. (2026-10-03: a priority-first pick took
same-day tickets while three tickets filed 2-3 weeks earlier sat untouched.)

The only things that go ahead of the oldest eligible ticket:
- its own blockers (`blocked_by` relations), and a ticket that unblocks queued work
- an `urgent` regression on a batch this run just shipped (stop-the-line, `core/pm/skills/stop-the-line.md` §1)
- the migration window (below), and `Rework` on a ticket already in flight

Skipping the oldest is allowed only for a reason you name in the pick announcement: file
overlap with an open PR (hold it, it is next once that PR lands), owner-gated (§2 check above),
schema outside the window, or a declared wait such as "after the next main release". "Lower
priority" is not a reason.

**An old ticket must be re-checked against everything filed after it.** Before claiming, list
newer tickets in the same area (same paths from `triage`, or same feature words in the title)
and read the ones that touch it. If a newer ticket already did it, changed the design, or
contradicts it: comment the evidence and close it (`Done` if shipped, `Cancelled` if
superseded), or move the decision into the description before claiming. Tell the engineer in
the brief which newer tickets to read. This is the second half of the owner's rule: old tickets
are worked first so they don't rot, and checked first so they aren't built against a design
that moved on.

**File-overlap is now a hard filter, not a tiebreak.** Two tickets touching the same shared
component/page, built in parallel, produce exactly the conflict-on-merge problem parallelism is
supposed to avoid without adding value — if a candidate's known area overlaps an already
in-flight ticket's area (read the in-flight ticket's worktree/branch name and any early
findings comment), skip it for *this* round; it becomes eligible again once the in-flight one
lands.

**Decide overlap from the PR's real file list, never from memory or a branch name.** Before you
hold a ticket or a PR for overlap, run `gh pr view <n> --json files --jq '.files[].path'` on the
PR you think owns the file and name the shared path in your announcement. No shared path means no
hold. (2026-09-30: one ticket was held for a file the other PR didn't touch, and another was
claimed, then un-claimed, on a guess.)

**Schema tickets: build in parallel, merge one at a time (owner, 2026-10-26).** If a candidate
ticket's own text signals a schema change (a new field, model or migration, or a prior worker
flagged it), these rules apply:

- **Schema tickets build in parallel when their models don't overlap.** Before you claim a second
  (or third) schema ticket, name the models each one adds or changes (from triage and the ticket
  text; ask a `scan` lane when it isn't clear). No shared model, table or enum → both build at
  once. A shared one → the later ticket waits until the earlier one's PR merges.
- **Every schema brief names the other schema tickets in flight and their models as off-limits**,
  and asks for an **additive-only** migration (new tables, new nullable or defaulted columns, new
  enum values) in **its own migration folder**, authored by hand per the repo's migration notes
  (`fleet.schema_notes`). A migration that drops, renames or rewrites existing data is not
  parallel-safe: that ticket builds alone.
- **Cap: at most `fleet.parallel_schema` schema tickets building at once** (default 2). They still
  count toward `fleet.parallel_workers`.
- **Non-schema work does not wait.** Fresh engineers keep filling slots, as in a real team where
  one engineer does the migration and the rest keep working. The file-overlap filter keeps them
  off the schema PRs' files (`gh pr view <n> --json files`), and their briefs list those files
  as owned.
- **The merge stays serial: one schema PR per train**, so a red trunk run points at one PR. The
  next schema PR in line then rebases onto the new trunk, **re-stamps its migration folder** so it
  sorts after trunk's latest one, runs the repo's deploy-style migrate on a **fresh** slot DB and
  the schema validator, pushes, and waits for green CI. That rebase is mechanical: it is yours
  (`core/pm/skills/merge-queue.md` §5), or a short engineer lane if the schema file conflicts.

(Before 2026-10-04 one schema ticket held ALL engineer picks. Until 2026-10-26 it still held every
other schema ticket from build to deploy, about 1.5 to 2 hours each. That day 10 of 22 new tickets
were schema, and oldest-first put an urgent prod fix ninth in line. The owner: "what if we have
tickets that need a db change, they cannot wait all that time per ticket." Two additive
migrations on different models don't collide; only their order on trunk matters, and the
re-stamp at merge fixes that.)

**The migration window, so schema tickets don't starve.** Waiting their turn only works if the
turn comes. Under oldest-first with a long approved queue it never did: six schema tickets sat blocked
through a whole three-day run. So:

- The window opens each time a train reaches `Done` and trunk is green, or a schema slot frees
  under `fleet.parallel_schema`.
- If an eligible schema ticket exists at that moment, it is **the next engineer pick**, ahead of
  priority order, and it takes its slot before any fresh non-schema pick.
- Testers, the merge queue and non-schema engineer picks keep running during the window.
- Each schema PR lands in a train of its own. Nothing else is merged in that train.
- Announce it: "schema: PROJ-320 (models Return, ReturnRule) building beside PROJ-331 (Branch), disjoint".

**Check the budget mode before you fill a single slot (`core/pm/skills/preflight.md` §0.6).** In CONSERVE or WIND-DOWN you fill
none — you land what is verified and stop picking. A slot you open now that cannot finish before
the window ends is worse than an idle slot, because it ends as an orphaned worktree and a ticket
claimed by nobody.

**Fill up to `fleet.parallel_workers` engineer slots** (never more than free `fleet.slots`). A
`Rework` ticket goes first by priority, but takes **one slot**, not all of them — fresh `Todo`
tickets fill the rest. A Rework engineer is always a **fresh session**, never the one that built
it and never the tester. Its brief points at the tester's Rework comment and any failing test
the tester pushed to the branch; it continues on the **same branch and PR**. A ticket that has
been sent to Rework twice in a row is worth flagging in your pick announcement (it's a data point
worth surfacing, not a reason to stop other work).

**After the third round, stop patching.** A ticket going into its fourth engineer round gets a
fresh `opus` engineer briefed to rebuild against written invariants, not to fix the last
finding:
- write the ticket's invariants (three to five, each testable) in a PM comment on the ticket,
  and in the brief
- the engineer re-reads the whole diff against them, lists every path and screen each one
  covers, with the test that proves it, and puts that list in the PR body
- every failing test the testers pushed must pass unchanged
- if the invariants don't fit the ticket's size, split it through the planner instead
(2026-10-28: tickets patched one finding at a time took up to 9 rounds. Each round fixed the
reported line and missed its sibling.)

**Announce every pick**, one line each, naming priority and what's skipped for it.

**Claim before spawning**: state → `In Progress`, assigned, for every ticket you're about to
spawn — in the same message/pass, not staggered, so a crash mid-claim is recoverable.

### New work and board shape: the planner plans, the Plane specialist files

You do not write or reshape tickets yourself. When the user brings new work (a feature, a bug
list, meeting notes), or the board has many small tickets on the same area:

1. Spawn `fleet-planner` with the request, the repo path and the fleet folder. It returns a
   plan file: one ticket per outcome, sized by `engineering/references/ticket-rules.md` §2 "Shape".
2. Show the user the plan's ticket list and totals (tickets before and after). Merging or
   cancelling tickets on a client board needs their yes.
3. Spawn `fleet-board` with the plan path and the approved list. It files, merges and links the
   tickets and reports the ids.
4. Pick from the result as usual.

Engineers and testers still set their own ticket's state and write their own comments.

---
