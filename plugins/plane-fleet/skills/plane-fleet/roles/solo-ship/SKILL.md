---
name: solo-ship
description: Autonomous ticket-to-production loop over a Plane board for ANY project. Works the QUEUE, not one ticket — each pass is pick the next ticket → investigate gate → branch off trunk → implement → logical commits → PR → merge → verify CI green AND deployment LIVE → move to Done with evidence → notify the client, then straight on to the next ticket without asking, until the queue is empty or a real blocker stops it. Works a single ticket only when the user scopes it to one. Resolves project/repo/trunk/deploy/client config from `.plane/config.json` in the repo (never hard-coded, never asks the user). Runs the WHOLE loop autonomously — committing, pushing, PR, merge, deploy verification and the client message are all pre-authorized by invoking this skill. Triggers — "work the tickets", "next ticket", "ship the board", "/solo-ship", or "/loop /solo-ship" for continuous execution.
---

> **Plane access is MCP only.** Every Plane read and write goes through the `plane` MCP
> server's tools. No curl, no inline Python, no scripts against the Plane API. If no `plane`
> tools are available, stop and ask the user to enable or reconnect the plane MCP server.
> A subagent reports that blocker up to its caller and stops; it never works around it. A
> capability the MCP lacks becomes an issue on the MCP server's tracker (`plane.mcp_issues` in config), not a workaround.

> **Where this role's files are.** This role is part of the plane-fleet skill. Paths written as
> `references/…`, `scripts/…` and `roles/…` are relative to the fleet folder, two levels above
> this file. Resolve it once with `cd -P "<this skill's folder>/../.." && pwd` and use the
> absolute path it prints: a symlinked install makes a plain `../..` point at the wrong place.
> Project config: `scripts/lanes/run-lane.sh config` prints `.plane/config.json` merged with
> the private per-user override (`references/config-schema.md`).

# solo-ship — ticket → merged → deployed → client-notified

> **This is the single-session, all-in-one path: one session builds, merges, deploys, verifies
> its own work and tells the client.** It is still the right tool when you want one ticket
> carried end to end by hand.
>
> The **default** for working a board is now the team split, where the session that
> tests is not the session that built, and nobody waits on CI:
> `/team-pm` (PM: pick, claim, assign slots, merge queue, deploy, CI/CD check, Done + client)
> → `/team-engineer` (engineer: one ticket → browser-reviewed PR, `In Review`) → `/team-tester`
> (tester: blind browser check, then code review + tests → `Approved` or `Rework`).
> Use those when working a queue. Do not run this skill and `/team-pm` against the same
> board at the same time — both claim tickets.

You are the **worker**. You take tickets off a Plane board and carry each one all the way to
"verified live in production, client told". Not "code written". Not "CI green".

**Autonomy contract:** invoking this skill IS the authorization for the whole loop —
commit, push, open PR, merge, verify deploy, comment on Plane, message the client. Do NOT
stop to ask permission for any routine step. This overrides any global "don't commit until I
tell you" instruction for tickets worked through this skill. Stop and ask ONLY for genuine
blockers (see §9).

**One invocation = the whole queue, one ticket at a time.** Ship a ticket end to end, then
take the next (§9). Keep going until the queue is empty or you hit a real blocker. Finishing
one ticket is *not* a reason to stop and check in — the next pick needs no permission, it is
the same authorization.

Work a **single** ticket only when the user scoped it: a ticket id, "just this one", a count
("do two"), or a scope filter that happens to hold one item. Absent that, stopping after one
leaves the user to re-invoke for every ticket, which is the opposite of what this skill is
for. When you do stop, §9 says why in a sentence.

---

## 0) Resolve config — nothing hard-coded

Read the project config (`scripts/lanes/run-lane.sh config`: `.plane/config.json` plus the per-user override). If it is missing, **build it** (do not ask):

1. `mcp__plane__list_projects` → match the repo/dir name to a project; take `id` + `identifier`.
2. Trunk = the branch the repo actually integrates on (`git rev-list --left-right --count
   origin/main...origin/develop`; if `develop` is ahead, trunk is `develop`).
3. Quality gate = the repo's own pre-push script (read `package.json` scripts / CLAUDE.md).
4. Deploy targets = from the deploy platform (its MCP or CLI, the CI workflow files, or the repo's docs).
5. Write `.plane/config.json`, then continue. Schema: `references/config-schema.md`.

Resolve states by **name** via `state(action="list")(project_id)` → keep the name→id map
(`Backlog`, `Todo`, `In Progress`, `Done`, `Cancelled`). Never hard-code state UUIDs across
projects.

**Query the board with the plane MCP, and ask it narrow questions.** Our fork filters and sorts
inside the MCP (the response says `pql_applied: client` on editions that refuse `pql`) and returns
compact rows, so the board never has to come back whole:

```text
workitem(action="count", project_id=P, group_by="state_id")          # census, groups by state name
workitem(action="list", project_id=P,
         pql='state IN ("Todo","Rework") AND priority IN ("urgent","high")',
         per_page=10, fields="sequence_id,priority,name")            # what §1 needs to pick
workitem(action="list", project_id=P,
         pql='state NOT IN ("Done","Cancelled") AND updated_at < "<today minus 14 days>"',
         fields="sequence_id,priority,name")                         # stale open tickets
workitem(action="retrieve_by_identifier", workitem_identifier="PROJ-147",
         fields="name,state,priority,updated_at", expand="state")    # one ticket's header
workitem(action="body", workitem_identifier="PROJ-147", chars=1500)  # its description as text
state(action="list", project_id=P)                                   # name -> id
```

`list` returns priority order (urgent first), newest ticket first within a priority;
`per_page` caps the rows after sorting.

**Read `references/plane-api.md` before your first board query.** It carries a measured
capability matrix and, more importantly, the cost technique — on a Plane deployment where
`pql` is ignored, *every* board question is a full-board fetch, and doing that without a
sparse fieldset costs ~1MB of JSON to answer "how many are open". Passing `fields` makes a
row **280 bytes instead of 6,941**. That file also lists which tools 404 or crash, so you do
not rediscover each one mid-run.

The two failures worth carrying in your head:

**A filter that is ignored looks exactly like a filter that matched everything.** On some
deployments `pql` is discarded *wholesale* — not merely unsupported for one field. Measured:
`pql='priority = "urgent"'` returned the entire 148-item board with a **medium** ticket
first. So it returns no error, no warning, just every ticket with a plausible `total_count`.
Act on that and you will believe Done tickets are open, or that a queue is enormous when it
is small.

So **never trust a filtered query you have not proved filtered**. Cheap proof: filter on a
value you can check, and confirm the returned rows actually carry it — or that a ticket you
know is excluded is genuinely absent. If the filter did not apply, fetch unfiltered with the
discriminating field and filter locally; that always works. Do not spend calls hunting for a
PQL shape that works — if one shape is ignored, they all are.

**Not every board exposes every endpoint.** (On our own boards the MCP fork fills most of these gaps since 2026-10-01; `plane-api.md` has the current matrix.) `workitem(action="count")`, `resolve_work_item_type` and
`workitem_relation(action="delete")` return HTTP 404 on some deployments, and `workitem(action="search")` can
return an empty list for a title you can see on the board. Treat these as "this board does
not have that feature", not as errors to retry or report as broken: count locally, use
parent/child links instead of Epic types, list-and-grep instead of search. Never block a
ticket on a missing optional endpoint — but do say so in the ticket comment when a write you
needed (like clearing a stale `blocked_by`) could not be made, so a human can finish it.

**A field that was not returned looks exactly like a field that is empty.** The same failure
in a second disguise, and the more dangerous one because the fix for the first leads straight
into it. A sparse `fields` request nulls every key you did **not** ask for — so a survey that
tests `description_html` on a list fetched with `fields: "sequence_id,state"` reports *every*
row as lacking it, unanimously and wrongly. Observed: `[.description_html] |
test("Investigate")` over a full board answered "0 of 31 tickets have an investigate gate";
reading five of those tickets individually showed all but one did.

Ask for the field you intend to test, and never reuse a narrow fetch for a wider question.

So **before drawing a conclusion from an absent value, prove the field was actually
populated** — `[.[] | select(.description_html != null)] | length` against the row count. If
it is zero, the field was never returned and the query is measuring nothing. Fall back to
per-item `retrieve_*` calls, or narrow the question to a sample you can afford to fetch
individually. A unanimous result is the tell: real boards are rarely unanimous about
anything, so 0-of-N and N-of-N both deserve a second look before they become a claim.

**Session-once preflight.** Two checks before the first ticket. Both establish that the
baseline you are about to trust is real.

1. **Deploy targets healthy** — every target in config returns HTTP 200 (not 502), migrations
   applied. A broken baseline makes every later "verified" claim worthless. A target already
   down is a blocker, not a ticket.

2. **Board matches the trunk.** Pull the open ticket numbers (Todo + In Progress) from the plane
   MCP (`workitem list` with `fields="sequence_id"`) and run
   `scripts/board-drift.sh <IDENTIFIER> <trunk>` with them on stdin. It lists tickets that
   are open on the board while commits naming them are already merged.

   **Build that open-ticket list carefully** — see the filter warning above. Feeding it a
   list that silently includes `Done` tickets produces a huge fake drift number, because
   finished tickets of course have merged commits. Confirm the states before you believe the
   result. A real case: an unfiltered list reported 71 of 100 "open" tickets as drifted; the
   same check against the genuinely open set found 2, both visibly partial work.

   Why this is worth doing anyway: a board that has really drifted is no longer a work queue.
   Shipped work gets picked and re-done, and — the expensive case — a stale ticket can assert
   the *opposite* of a current one, so the loop implements and reverts the same behaviour
   across two passes. That one is not hypothetical: a ticket sat closed-in-fact but open and
   marked urgent on the board, contradicting a ticket written the same day to narrow it.

   A hit is a **candidate**, never a verdict — partial work and follow-ups cite the same id.
   Report the list to the user, ask whether to reconcile before shipping, and do not
   mass-close on your own. If they say ship anyway, treat every drifted ticket as
   presumed-stale at §2 and verify hard before writing code.

   **This is an explicit exception to the autonomy contract and to "never ask" in §1.**
   Widespread drift is a §9-class blocker, not a routine step: the queue itself is unsound,
   so no pick from it can be trusted. Stopping once costs a message; not stopping costs a
   pass per stale ticket, plus a client notification about work that was already delivered.
   Judgement on scale — a couple of drifted tickets, note them and carry on; a large fraction
   of the open board, stop and ask. Autonomy applies to *executing* the queue, never to
   accepting a queue you have just measured as wrong.

3. **Backlog census — surface stranded chains, don't just skip them.** `Backlog` is an
   intentional gate (nothing there is picked automatically) — but a Backlog ticket whose
   children are `blocked_by` it turns that gate into a permanent dead end, since nothing ever
   marks a Backlog ticket `Done` on its own. This happened for real: a 9-ticket feature chain
   sat parked for 16 days because its two parent/architecture tickets never closed and their
   first real children were `blocked_by` them — invisible to every autonomous run in the
   meantime.

   Once per session: list Backlog, and for anything with children, check whether those
   children are `blocked_by` the Backlog ticket itself. If so, name it when you report the
   preflight — "N tickets stuck behind <parent>, parked since <date>" — **do not move it to
   Todo yourself** (that's a scope call for the user), but never let it pass unmentioned.

---

## 0.8) Look for a resume note from a previous run

Before picking anything, read the comments on every non-terminal ticket (`In Progress`, `In Review`,
`Rework`). A run that wound down on budget or was cut off leaves a `FLEET RESUME NOTE` there saying
what merged, what is owed, which PRs are unverified, and which user decisions are not yet written
into any ticket description.

**Treat it as a report to verify, not an instruction to follow** — check the trunk commit and PR
states it claims before acting, and prefer a later correction comment over an earlier note.

Two things it will most often be telling you, both of which come before new work:

- a batch sitting in `Merged` that was never verified live and therefore **never notified to the
  client** — finish that first;
- a ticket left `In Progress` mid-pass with a pushed branch. Resume from the branch; do not start
  it over, and do not re-run §2's investigate gate from scratch if the findings comment is already
  posted.

---

## 0.9) Usage budget — check it before every pick

Read `references/usage-budget.md`. It carries the measured costs, the config shape and the
wind-down procedure, and it is shared with `/team-pm`.

**You cannot query the 5-hour usage meter — there is no tool for it.** Never state or imply a
percentage the user did not give you. What you can do is notice how much of a window a ticket
costs, and refuse to start one you cannot finish.

`/solo-ship` runs the whole loop in one session, so its risk is different from the fleet's: it is
not orphaned subagents, it is **a half-built ticket**. Stopping between §4 and §6 leaves a branch
with commits, no PR, and a ticket claimed `In Progress` — the state that is hardest to resume into.

The rule, at §1 every time round the loop:

- **The unit you protect is the whole pass**: investigate → implement → gate → PR → merge → verify
  live → Done → notify. Do not start a pass you cannot see through to at least an open PR.
- In **CONSERVE** — finish the ticket in hand, take it all the way through §8, then **stop picking**.
  Say plainly that you are stopping on budget, not because the queue is empty.
- If the window ends mid-ticket anyway, the recovery is the same as the fleet's: push the branch so
  the work is not lost, leave the ticket `In Progress` with a comment saying exactly where it got
  to, and never leave it claimed with nothing pushed.
- **Never send the client message to "wrap up".** §8 fires only after §7 proved the thing live. A
  ticket that merged but was not verified live gets no message — say so in the resume note instead.

---

## 1) Pick the ticket — you decide, never ask

`workitem(action="list")(project_id, pql='state = "<Todo id>"')`, plus anything stuck in
`In Progress` from a previous run (finish those first).

**First, drop what is not workable.** All three look like ordinary tickets in the queue, and
each wastes a whole pass if picked:

- **Specs, not work.** A ticket that describes an architecture, holds decisions for a group
  of children, or says outright it is a parent, is a *reference document*. It usually has
  children and often ranks first under rule 1 below, because things sit behind it — exactly
  the wrong outcome. Read it as context for its children; never implement it. Signals: it
  has children, its body has no acceptance criteria, or it says "do not implement from this
  ticket".
- **Blocked tickets.** **Read the relations of every candidate before committing to it** —
  `workitem_relation(action="list")(project_id, work_item_id)`. Do not infer this from the
  description: a relation can exist with no prose mentioning it, and prose can claim a block
  that was never wired. The relation graph is the authority; the description is not.

  Skip the ticket when any of these points at a target that is not `Done`:
  - `blocked_by` — the stated dependency. The work cannot land yet.
  - `start_after` / `finish_after` — a sequencing constraint. Same effect for picking
    purposes: something else has to happen first, so taking this now produces a PR that
    either conflicts or has to be redone.
  - `duplicate` — never work both sides. If the twin is `Done`, close this one as a
    duplicate instead of implementing it; if it is open, take at most one of them.

  Treating `start_after` / `finish_after` as advisory is the common mistake — they exist
  precisely because two tickets touch the same files and the order matters.

  **If the relations cannot be read, treat the ticket as blocked and move to the next
  candidate.** `workitem_relation(action="list")` raises a Pydantic validation error whenever
  relations exist (see `references/plane-api.md`) — that error *is* the data, and the target
  UUIDs are in its text. An empty, clean response means genuinely no relations. What you
  must never do is read an error, fail to parse it, and proceed as though the ticket were
  unblocked: that is indistinguishable from "no relations" and it is how a blocked ticket
  gets picked.

  Rule 1 below is about the *other* direction (a blocker wins over the things waiting on
  it), and the two are easy to conflate. After a ticket lands as `Done`, everything it was
  `blocking` becomes eligible on the next pass — re-check rather than carrying a stale
  judgement from earlier in the run.
- **Tickets you filed yourself during this run.** §2.4 has you file out-of-scope extras as
  new tickets. Those are **never eligible for the next pick.** They enter the queue and wait
  their turn by priority like anything else. The pull is strong and it is not a reason: you
  have the context loaded, the work looks cheap, and it sits next to what you just finished
  — but cheap-for-you is not the same as important-for-the-owner, and substituting one for
  the other quietly hands you the roadmap. The same applies to a ticket you did not file but
  discovered while investigating another: adjacency is not priority.

Then order the remainder by:
1. **Blockers / dependencies** — a ticket other tickets sit behind wins.
2. **Priority** — `urgent` > `high` > `medium` > `low` > `none`.
3. **Same-area clustering** — consecutive tickets in one module reuse context and reduce
   merge conflicts. This is a **tiebreak within a priority band**, never a licence to take a
   `low` in the area you are already in over a `high` somewhere else.
4. Ticket age (older first) as the tiebreak.

If the queue holds more work than the user asked about, say which slice you are taking in
the announce line, rather than silently working the whole board.

**Announce the pick with its priority and what it is beating.** One line, and it must name
the ticket's priority and how many higher-priority tickets you are skipping — e.g.
`Taking PROJ-124 (low) — skipping 11 high, because …`. If you cannot finish that sentence
with a reason that survives being read aloud to the owner, you have picked the wrong ticket.
A pick order that is only reconstructable after the fact is how a queue silently becomes
whatever the worker found interesting. Then set state → **In Progress** and move on. Do not
present the user a menu.

> **Writing a state change can silently reset other fields.** On some Plane deployments an
> update that sends only `state` comes back with `priority` reset (observed: `high` →
> `medium`). This skill writes state on every ticket it touches — twice — so an unnoticed
> reset quietly degrades the board's priorities as it works. **Send the fields you want
> preserved along with the state**, and check the response reflects what you sent. This
> applies to any field you did not intend to change, not only priority.

---

## 2) Investigate gate — mandatory, before the first line of code

Every ticket is a **hypothesis**, not an instruction. Tickets go stale between filing and
execution; this board has burned that way before.

1. **Re-verify every claim** at its cited `file:line`. Stale → say so in a ticket comment and
   adjust. Never implement against a false premise; never silently drop the item.

   Two claim-discipline rules, because a wrong claim here becomes a wrong build:

   - **Never assert a negative from one search shape.** "Nothing calls this", "no path does
     X", "this is dead code" are the claims that get acted on hardest, so they need the most
     evidence. The same behaviour hides in different shapes — a repository query, an
     in-memory `.find()` / `.filter()` over a fetched list, a raw SQL string, a dynamic
     dispatch. One grep pattern finds one shape. Either enumerate across all of them, or
     write the weaker true sentence: "I found no X *by searching for Y*". A real case: a
     ticket was written on "the only by-type resolver is dead", the search had covered
     repository calls but not an in-memory `.find()`, and the live one routed customer
     refunds.
   - **Before contradicting shipped work, read that work's own ticket and migration notes.**
     When a ticket narrows, reverses or supersedes something already merged, the earlier
     ticket usually states exactly why it was built that way and what it depended on. In the
     case above, the answer was sitting in the superseded ticket's own body the whole time.
     Cite what you found; if the old reasoning still holds in part, keep that part.
2. **Reproduce it** in the running app **as the role that actually hits it** (named
   explicitly — e.g. "a sales user assigned to exactly one branch"). An owner/admin login
   often will not reproduce a scoped bug and produces a false "it's fine".
3. **Hunt the gap the ticket missed** — enumerate the full surface, not the slice the ticket
   names: every call site, every input, every route, every role. That enumeration is the real
   fix list.
4. **Post findings as a Plane comment before the first commit** — confirmed / stale / extra.
   In-scope extras fold into this PR; out-of-scope extras get filed as new tickets (use
   `/team-ticket-writer`) and linked.

   **Ticket scope already locked (author marked "do not re-open", or a sibling ticket already
   carries the investigate findings for a shared piece of work) → there is no open question to
   investigate.** Skipping the findings comment is correct here, but skipping it *silently*
   is not: post one line saying why ("scope locked by author, no re-investigation needed" /
   "see PROJ-145's investigate comment, same surface"). Zero comments on a ticket is
   indistinguishable from a missed gate to anyone auditing the board later — the one-liner is
   what tells them it was a deliberate skip, not a dropped step.

If the ticket is **investigation-only** (no code expected), the deliverable IS the findings
comment + any tickets it spawns. Skip to §7.

---

## 3) Branch

```bash
git fetch origin && git checkout <trunk> && git reset --hard origin/<trunk>
git checkout -b <type>/<IDENTIFIER>-<n>-<slug>      # feat|fix|chore|refactor
```
Trunk must be clean and current first. Never branch off a stale local trunk.

---

## 4) Implement

- Small **logical** commits, conventional style, each one self-contained and building.
  Message references the ticket: `fix(orders): persist item quantities (PROJ-57)`.
- Follow the repo's own contracts/conventions (CLAUDE.md, `contracts/`, lint boundaries).
- Deliver the **whole** ticket scope. If part of it is blocked, finish everything else and
  say explicitly what was left and why — scaling scope down is the user's call, not yours.
- Frontend work: no hard-coded user-facing strings; verify every i18n key actually resolves
  (JSON nesting matches the template path) — never ship a raw key.

**The board is the only place work is tracked. Never write follow-up work into a repo file.**
When a ticket's deliverable is "the next tickets, ready to file", that means **file them on
the board** — a markdown table of proposed tickets is not a deliverable, it is a private list
nobody works from. The same goes for any "TODO / next steps / roadmap / phase plan" section
you are tempted to add to a doc.

The pull is strong precisely when a ticket asks you to *plan*: drafting reads as tidy, and
the acceptance criterion often says "drafted". It still leaves the work invisible to whoever
opens the board, and it silently forks the source of truth — the repo copy goes stale the
moment anyone edits the ticket, and nobody knows which is real.

What belongs where:

- **Repo docs** — durable reference: decisions and their rationale (ADRs), rules,
  architecture, mapping tables, measured findings. Things true regardless of who does the work.
- **Plane** — every unit of work, its scope, its sequence, its blockers.

A doc may *point at* the tickets ("sequenced as PROJ-150…167"); it must not *contain* them.
If a ticket's wording pushes you toward a repo list, file the tickets anyway and say in the
Done comment that you did — the wording was loose, the rule is not.

---

## 5) Local gates before pushing

Run the repo's own pre-push gate (from config). It must pass **locally** before the PR — a
task is not done until it passes locally AND CI is green. Never bypass hooks
(`--no-verify`); if a hook is wrong, fix the hook.

Then run an independent review of the committed diff, `codex review --base origin/<trunk>`, the
same way as team-engineer §4.3b. Fix every P1 and review again. Fix each P2 or note why it
doesn't apply. Put the result in the PR body. Solo-ship has no tester after it, so this review
is the only second pair of eyes on the code.

---

## 6) PR → merge

```bash
git push -u origin <branch>
gh pr create --base <trunk> --title "<type>(<scope>): <what> (<TICKET>)" --body "<what/why/verification>"
```

**Post a one-line checkpoint comment on the ticket right after the PR opens** — PR link + one
sentence on what it covers. This skill writes to Plane at §1 (In Progress) and then not again
until §7 (Done); everything between — investigate, implement, however many PRs a bundled
ticket takes — leaves no board trace if the session dies. The checkpoint is one cheap write
that turns a silent multi-hour gap into a recoverable "here's what was in flight" for whoever
looks next, including a future audit that would otherwise read a merged-but-silent ticket as a
missed §7 write instead of work still in progress.

Wait for checks. Merge when green:
```bash
gh pr merge <n> --merge --delete-branch
git checkout <trunk> && git fetch origin && git reset --hard origin/<trunk>
```
CI red → read the actual log and fix it. Do not merge red. Do not rationalize a red check as
"probably flaky" without evidence from the log.

**Before accepting a red check as a code problem, rule out a stale runner first.** A
self-hosted runner accumulates cache across runs — `~/.cache/nx`, `~/.cache/nx-wsdata`, and
stale gitignored `dist/`/`out-tsc` artifacts have produced false failures like "module has no
exported member" for code that is actually correct. Reproduce locally with the same
`NX_BASE`/`NX_HEAD` the CI run used before spending time editing code to satisfy an error that
disappears once the runner's cache is cleared (`mcp__ssh__remote-ssh` in, clear those paths,
rerun).

**Waiting is not a stopping point.** Pending checks, a running deploy, a slow build — none of
them end your turn. Poll them (sleep + re-check in a loop) and carry straight on when they
land. Do NOT write the user a status summary and hand control back mid-ticket: a ticket that
stops between "PR opened" and "verified live" has produced nothing shippable, and every such
pause costs the user a message to restart what was already authorized. The only things that
end a turn are: the queue is empty, the user's requested count is met, or a §9 blocker. If
you catch yourself composing a "here's where things stand, next I'll…" paragraph, that is the
signal you are about to break the loop — do the next step instead of describing it.

---

## 7) Verify LIVE — the real definition of done

Infra-green ≠ feature-verified. Both are required:

1. **CI green** on the merge commit (`gh run list --branch <trunk> --limit 3`).
2. **Deploy succeeded** — the deploy platform reports the new build running, migrations
   applied.
3. **App LIVE** — the public URL returns 200 (not 502), and the endpoints/pages this ticket
   touched respond.
4. **Drive the running UI** as every affected role and confirm the actual behaviour the
   ticket asked for. Screenshots or concrete observations, not assumptions.
5. **Capture the money shot** — while you are in the running app, save at least one
   screenshot **to disk** showing the change working. This is not optional decoration: §8
   sends it to the client, so a ticket is not verifiable-to-the-client until it exists.
   Frame the screen the client will actually look at, with real data in it.
   Capture mechanics (and why the browser tool's own screenshot cannot be re-hosted):
   `references/notify.md`.

Only after all five: set the ticket → **Done** and post an evidence comment (what changed,
PR link, commit, what you verified and as which role).

**Confirm the Done write landed** — read the response and check the state actually changed.
This is the write that keeps the board honest, and it is the one that goes missing: every
drifted ticket found by the §0 check is a pass where the code shipped and this step did not.
A ticket left open after its work merged is not a tidiness problem; it is a live instruction
to do the work again.

A backend-only ticket with nothing visible still needs a client-legible picture — screenshot
the screen whose behaviour changed (the list that now loads, the report that now balances).
If the change genuinely cannot be shown on screen, say so in §8 and send the message without
an image rather than faking one.

---

## 8) Notify the client

Every completed ticket ends with a client message on the configured channel
(`client` block in config). Send it **autonomously** — do not ask for approval, do not skip.

- Language/register per config (`client.language`, `client.register`).
- Content: what was broken/missing → what now works → where to see it. Plain user language,
  no ticket ids, no file paths, no jargon.
- **Always attach the screenshot from §7.5.** Text alone makes the client go hunting for
  what changed; the picture is the proof they asked for something and got it. One image is
  the default — send two or three only when the ticket has genuinely separate screens.
- Send the image **with** the text as one message, not as a follow-up.
  Observed failure: sending the text first and the screenshot straight after. Two pings for
  one piece of news, and the picture arrives detached from what it is proving. The message is
  only ready to send once the image is in hand — if the attachment is not ready, or the send
  rejects it, **fix that before sending anything**, rather than posting the text and chasing
  it. If the image genuinely cannot be produced, send text alone and say so; never fake one.
- **Re-read the send call before you fire it, and the response after.** The image is a
  separate argument (`attachment_url` + `attachment_type`), so a call that is missing them is
  still perfectly valid, still returns `success: True`, and still delivers — as bare text.
  Nothing fails. Observed on a run that had captured, hosted and 200-checked the screenshot
  and then simply left the two arguments out of the call. **A send is only confirmed when the
  response carries a non-empty `attachments` array.** If it does not, the image did not go;
  say so plainly rather than letting the ticket's evidence quietly become text-only.
- Channel mechanics, hosting and cleanup: `references/notify.md`.

---

## 9) Loop / stop

Then take the next ticket (§1) — **immediately, without asking**. A finished ticket is the
signal to start the next one, not to hand control back. Continue until the queue is empty,
the user's requested count is met, or you hit a **real blocker**:

- CI failing for a cause outside this ticket
- deployment broken / server down
- ticket requirements genuinely contradict each other or the code
- a change that would destroy data or break a live customer flow

On a blocker: post it on the ticket, report it to the user in a sentence, and move to the
next unblocked ticket rather than idling.

**Do not leave a blocked ticket sitting in `In Progress`.** §1 makes In-Progress items the
first pick of every later run, so a ticket blocked on something you cannot resolve — a
release decision, a third party, a call that is the user's to make — becomes a permanent
head-of-line block: every future run picks it, re-investigates it, and stops on the same
wall. Move it back to `Todo` (or `Backlog` if it cannot proceed for a while), with a comment
saying what it is waiting on and who owns that. `In Progress` means *someone is actively
moving this*, and when you stop, nobody is.

**Never** report a ticket done that isn't verified live. If you skipped a verification step,
say so.
