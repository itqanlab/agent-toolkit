> **Plane access is MCP only.** Every Plane read and write goes through the `plane` MCP
> server's tools. No curl, no inline Python, no scripts against the Plane API. If no `plane`
> tools are available, stop and ask the user to enable or reconnect the plane MCP server.
> A subagent reports that blocker up to its caller and stops; it never works around it. A
> capability the MCP lacks becomes an issue on the MCP server's tracker (`plane.mcp_issues` in config), not a workaround.

> **Where the fleet's files are.** Paths written as `core/…` and `engineering/…` are relative to
> the fleet folder: the one that holds the fleet's `SKILL.md`, three levels above this file. Resolve
> it once with `cd -P "<this file's folder>/../../.." && pwd` and use the absolute path it prints.
> Project config:
> `core/scripts/fleet config` prints `.plane/config.json` merged with the private per-user
> override (`core/references/config-schema.md`).

# write-ticket — tickets an unattended agent can execute

A ticket here is not a note to a human who will ask follow-ups. It is the **complete brief**
for an agent that will pick it up cold, with no access to you. Two consequences drive
everything below:

- **No open questions.** Every ticket states decisions. If something is genuinely undecided,
  decide it yourself with a stated rationale, or make the decision itself the ticket
  (kind: investigation) — never leave "should we X or Y?" in the body.
- **The body is the whole context.** Comments get skipped by relay agents. Pointers to
  shared docs get skipped. Everything the worker needs goes in `description_html`.

---

## 0) Resolve the board

Read the project config (`core/scripts/fleet config`; schema in `core/references/config-schema.md`) → `plane.project_id`,
`identifier`. Missing → `project(action="list")` and match the repo/dir name; write the file.

`state(action="list")(project_id)` → name→id map. New tickets land in **Todo** (or **Backlog** only if
the user explicitly says "not yet" / "not this cycle" for *this specific ticket*).
`label(action="list")(project_id)` → attach the matching area label if one exists; create one only when
the user names it.

⚠️ **Never file a `[Decision needed]`, `[Investigate]`-titled, or `kind: investigation` ticket
into Backlog.** `Backlog` is never auto-picked by the PM or solo mode (`core/solo/role.md`) — nothing
promotes a ticket out of it on its own. A ticket that exists specifically to resolve an open
question needs to be picked up and worked, which means it goes in **Todo**, priority set from
how much the open question is blocking. Filing it into Backlog "because it's not ready to
implement yet" is exactly backwards — investigation tickets are ready to *investigate* the
moment they're filed; that's the whole point of the `investigation` kind (§2). This is a real,
observed failure mode: decision-needed and investigate tickets accumulate in Backlog across
projects because filing them there feels like the safe default, and then nothing ever resolves
them because Backlog is a gate no automated run opens by itself.

---

## 1) Investigate BEFORE you write

Do not transcribe a complaint into a ticket. A ticket built on an unverified claim wastes the
worker's whole run.

- Reproduce or locate the actual behaviour in the codebase.
- Get **real `file:line` citations** for the cause and every touch point. Never invent a path
  or guess a line — grep it.
- Enumerate the full surface (all call sites / routes / roles / inputs), because that
  enumeration becomes the worker's fix list.
- If it turns out to be already fixed, or the reported cause is wrong, say so and file the
  ticket that reflects reality — or file nothing and report why.

### Sweep-scope tickets: enumerate now, not later

**Hard rule: no vague scope word ships in a ticket.** Before `workitem(action="create")`, check your title,
§3 and §5 for these words: *everywhere, every page, every screen, all pages, all screens, across
the app, the whole app, all places, wherever, etc., and so on, similar places.* Each hit must be
replaced by the list it stands for: "the 6 screens below", then the 6 screens with `file:line`.
A hit you can't replace means you haven't done the search yet, so do it now. This applies to
every ticket from every source: owner requests, meeting dumps, and follow-ups filed by engineers
and testers. The PM's pre-pick scan (the triage action's `vague_scope` field) flags any ticket
that slips through, and it goes back for its list before anyone claims it. (A "use one digit style everywhere"
ticket failed test twice because each engineer fixed only the places they looked at.
Rework is the most expensive thing on this board, and this is its cheapest fix.)

**"Every X in the app" / "all pages" / "everywhere, literally" is a scope, not an
instruction to search.** If the requirement uses language like this, the filing pass must
produce the actual list of every instance — grep/glob it, read each hit, confirm it's a real
match — **before writing the ticket**. Do not write "audit the whole control set" or
"enumerate every filter bar before starting" and leave the search itself for the worker.

This is not optional politeness — it is the single highest-leverage thing separating a ticket
that lands clean from one that comes back `Rework`. Two tickets shipped 2026-08-22 without
this (`audit the whole control set`, `applied to every filter bar... literally`) both came
back from tester for missing an instance the filer never enumerated — one missed
control, one missed page — after a full worker session each. A worker's own mid-implementation
audit is bounded by whatever search *they* think to run; it is not a substitute for the filer
having already run one. Paying for the grep once at filing time (bounded, cheap) beats paying
for a wasted worker session + a failed verify pass + a second worker session + a second verify
pass to find the same instance.

**What this changes downstream:**
- §3 Required behaviour states the count and lists every instance found, each with a real
  `file:line` — "8 pages, all listed below," not "all pages." A worker implementing against a
  named list can't silently stop at instance 6 of 8; a worker implementing against "everywhere"
  can, and won't notice.
- §5 Definition of done checks off that same literal list — "each of the N items above,
  verified live" — never a restatement of "the whole app," which is unfalsifiable by
  construction. tester audits against this same list; if the filer's enumeration and
  the ticket's checklist match, a partial implementation is caught by counting, not by the
  verifier having to rediscover the surface from scratch.
- If you genuinely cannot be certain the search was exhaustive (a dynamic/generated surface, a
  pattern that might be invoked reflectively), say so explicitly in §3 and give the worker the
  exact search command/method to re-run and reconcile against — never silently fall back to
  "find them all" with no starting list.

### Third-party behaviour: read its source, don't assume it

When a ticket depends on how a library, SDK or external API behaves (an error handler, an
interceptor, a webhook, a retry policy), read the installed code in `node_modules` (or the
vendor's source) at filing time and cite it the same way you cite repo code, e.g.
`node_modules/@sentry/angular/.../errorhandler.js:52 unwraps HttpErrorResponse before
captureException`. If the behaviour can't be settled by reading, file a short `investigation`
ticket first, and file the build ticket from its findings.

Why: 2026-10-16, an error-filter ticket went through three rework rounds. One of them came from Sentry's
Angular error handler unwrapping `HttpErrorResponse` before our filter saw it. Ten minutes in
`node_modules` at filing time would have put that in the ticket.

---

## 2) Pick the kind

| kind | when | deliverable |
|---|---|---|
| **implementation** | the change is known and decided | merged PR, verified live |
| **bug** | something is broken; cause verified | merged fix + the repro proven gone |
| **investigation** | the decision, root cause, or scope is unknown | findings comment + spawned tickets, no code required |

**Size it before you write it.** The limits are in `engineering/references/ticket-rules.md`
§2:
- **Target:** one feature area, up to about 10 files and 500 changed lines.
- **Mechanical work** (table migration, deletion, rename): up to about 20 files.
- **Over 20 files or 2000 lines:** split it before filing.
- **Sweeps:** one feature folder per ticket, at most about 15 files.
- **Floor:** under about 150 lines doesn't get a ticket of its own. Add it to a sibling ticket
  in the same area, or to a batch ticket (all small CI/gate edits together, all small e2e
  fixes together), unless it's urgent or unblocks trunk.
- **Shape:** one outcome per ticket, end to end. Schema, server and client for one feature go
  in one ticket; never split by layer while the whole is under the ceiling. Siblings on the
  same screen or component go together. See `engineering/references/ticket-rules.md` §2 "Shape".

List the files you expect each ticket to touch in its body, so the PM can check the size at
pick time. Why: every ticket carries a fixed cost (a median $2.9 under 50 changed lines,
measured 2026-10-25), and size drives rework. Rework rises from 5%
under 200 lines to 25% at 500 and more, and to 42% at 21 or more files (measured 2026-10-05).

**Check for a standing sweep first.** If the report is one more instance of a pattern that
has an open "Sweep: ..." ticket on the board, add it to that sweep's
"Known instances" instead of filing a ticket. Post-release checks go on the "Release
checklist" ticket.

---

## 3) Ticket body template

`description_html` — every section, in this order. Adapt the wording, keep the structure.

```html
<h2>0. Investigate before you implement — mandatory gate</h2>
<ol>
  <li><b>Re-verify every claim</b> at its cited file:line below. Stale → say so in a comment
      and adjust. Never implement against a false premise, never silently drop the item.</li>
  <li><b>Reproduce it</b> in the running app <b>as &lt;the exact role&gt;</b> — e.g. "a sales
      user assigned to exactly one branch". An owner login will not reproduce this and
      creates a false "it's fine".</li>
  <li><b>Re-run the enumeration below and confirm it's still exhaustive</b> — code moves
      between filing and pickup. If you find an instance §3's list missed, add it, implement
      it, and say so in the findings comment. This step is a re-check against a list that
      already exists in §3, not the worker's first search — see "Sweep-scope tickets" below.</li>
  <li><b>Post findings as a comment before the first commit</b> — confirmed / stale / extra.
      In-scope extras fold into the PR; out-of-scope extras get filed and linked.</li>
</ol>

<h2>1. Symptom</h2>
<p>What the user sees, in their words. Include the exact error text / screenshot if given.</p>

<h2>2. Root cause (verified)</h2>
<p>What actually causes it, with <code>path/to/file.ts:123</code> citations. Say which parts
you verified and which are hypothesis.</p>

<h2>3. Required behaviour (decided)</h2>
<ul><li>Statements, not questions. Each one testable. For a sweep-scoped ticket ("every X"),
this is the literal enumerated list from the "Sweep-scope tickets" rule below — state the
count ("N instances, all listed:") and cite each one's <code>file:line</code>, not a
restatement of "everywhere."</li></ul>

<h2>3b. Must not happen</h2>
<ul><li>Concrete bad inputs with the exact result that must NOT occur, one per line. Each is a
test the engineer writes and the tester drives. Example: "a 5xx request carrying an
<code>x-api-key</code> header reaches Sentry with no value for that header". Not "scrub
PII".</li>
<li><b>Real path to drive:</b> name the entry point the tester must use in the running app
(e.g. "an <code>HttpClient</code> call subscribed with no error callback"), not a function to
call directly.</li></ul>

<h2>3c. Invariants and every path they cover</h2>
<ul><li>Three to five rules that must hold after the change, each one testable. Example: "the
refund on screen equals the refund booked, to the cent, for any selection".</li>
<li>Under each rule, every path that can break it, with <code>file:line</code>: every writer
of the field, every booking path, every screen that shows the value. Find them with a search
and paste the search.</li>
<li>Any rule the owner has to decide (which event to audit, what happens on a timeout) is
decided here, not during review.</li></ul>

<h2>4. Scope</h2>
<p><b>In:</b> … <b>Out:</b> … (out-of-scope items name the ticket that owns them)</p>

<h2>5. Definition of done</h2>
<ul>
  <li>Every item in §3 verified <b>by driving the running UI</b> as &lt;each affected role&gt;
      — not "the endpoint returned 201", not "CI is green". For a sweep-scoped ticket: every
      one of the N listed instances checked off by name, not "the whole app looks right."</li>
  <li>Local quality gate passes, CI green, deployment verified live.</li>
  <li>No hard-coded user-facing strings; every i18n key resolves (no raw keys).</li>
  <li>Evidence attached to this ticket.</li>
</ul>
```

§3's enumerated list is **never boilerplate** — it is the single highest-value part of the
ticket. Do the search now; don't defer it to §0.3, which is a re-check, not first discovery.

**§3b is required whenever the ticket touches security, privacy, money, auth, or an external
service.** Testers judge against the ticket. A rule that isn't written down is a rule nobody
checks, and the first place it surfaces is the group review, after a full engineer and tester
round. On 2026-10-15 all 5 group-review defects on the two Sentry tickets were missing
must-not lines.

**§3c is required on money, concurrency and audit tickets.** These are the tickets that
went round after round: each review found the same rule broken on one more path. A rule left
to be decided in review costs a full engineer and tester round each time it moves. The PM
turns §3c into the focused review prompt (`core/pm/skills/spawn.md`).

**Red-team the draft before filing (§3b tickets only).** Run one short pass on the draft
body, for example `codex exec "Read this ticket. List the ways an engineer could satisfy every
line of it and still ship something broken, insecure or leaking data. Concrete inputs only."`
with the body piped in. Turn each real answer into a §3b line. Skip answers that are out of
scope or already covered.

**Scope already locked → say so explicitly instead of writing the 4-step gate.** When you're
filing a split of a ticket you (or a sibling ticket) already investigated — e.g. "2/2" of a
piece whose "1/2" carries the investigate findings — there is no open question left for the
worker to re-investigate. Replace the `<h2>0. …</h2>` block with one line naming why:

```html
<h2>0. Scope locked — no re-investigation needed</h2>
<p>Findings already posted on PROJ-145 (same feature, server half). This ticket is the
client half of the same decided scope.</p>
```

Without this, solo mode (`core/solo/role.md`) has to infer the skip mid-run and the ticket sits with zero
comments until the worker decides on its own whether that's a missed gate or a legitimate
one — decide it here instead, at filing time, where you actually have the context.

---

## 4) File it

### First: never rewrite a ticket that is already being worked

Before you EDIT an existing ticket's description (as opposed to filing a new one), check its
state. **If it is `In Progress`, `In Review`, `Merged` or `Rework`, do not touch the
description — add a COMMENT instead.**

Plane enforces nothing here: any ticket can be edited in any state, at any time, and a claimed
ticket looks exactly like an unclaimed one. So this is a convention you have to keep
deliberately.

Why it matters: a worker builds against the description as it read it, and pre-merge verify
judges the work against the description as *it* reads it. Rewrite the text in between and
correct work gets failed for a requirement that did not exist when it was built. This happened:
one ticket's description reversed from "do NOT include a `shared/` folder" to requiring
one, while its PR was open and green. The work was fine; the spec had moved.

A comment reaches the same people, survives the rebuild, and lets the manager decide whether it
is this ticket's scope or the next one's. If the change is big enough to need a new description,
say so in the comment and let the ticket return to `Todo` first.

Filing a genuinely NEW ticket is always fine, whatever else is in flight.

```
workitem(action="create")(project_id, name, description_html, priority, state=<Todo id>, labels=[…])
```

⚠️ **`description_html` takes RAW HTML — never escape the tags.** Sending `&lt;h2&gt;` stores
the entities verbatim and the ticket renders as visible markup, unreadable to whoever picks
it up. Nothing errors; the write reports success. The parameter name plus the JSON-string
context makes escaping feel careful — it is not.

**Read the response back:** a correct description returns wrapped in `<div><p>…`; an escaped
one returns `<span>&lt;p&gt;…`. If it is wrong, fix it immediately with `workitem(action="update")`
(same content, unescaped). Escape only angle brackets the reader should see — a code sample
containing `<app-card>` needs `&lt;app-card&gt;` *inside* a real `<code>` tag.

- `name`: one line, imperative or symptom-first, no ids. e.g.
  `Transfer lifecycle: quantities and item statuses are never persisted`.
- `priority`: `urgent` (live broken / data loss) · `high` (blocks a role's daily work) ·
  `medium` (wrong or ugly, workaround exists) · `low` (polish).
- Dependencies: set `parent` for real parent/child, and cross-reference sibling tickets by
  identifier in §4 Scope.

  ⚠️ **Prose is not a dependency.** An autonomous worker (solo mode (`core/solo/role.md`)) picks by
  **`blocked_by` relations only** — "Blocked by PROJ-136" in the description does nothing,
  and the ticket gets picked and built against an unbuilt foundation. If a ticket genuinely
  cannot start yet, set the relation:

  ```
  workitem_relation(action="create")(project_id, work_item_id=<this ticket>,
                            relation_type="blocked_by", issues=[<blocker id>, …])
  ```

  **It returns no output on success** — indistinguishable from a no-op. Read it back with
  `workitem_relation(action="list")`; that call fails Pydantic validation, but the error enumerates
  the related IDs, so N errors is a confirmation of N relations. Write the dependency in the
  prose *as well*, for the human reader — but the relation is what actually gates the work.

  ⚠️ **Never `blocked_by` a parent/architecture ticket.** the PM and solo mode (`core/solo/role.md`)
  explicitly drop parent docs with children from their pick queue (they're specs, not
  workable), and nothing ever marks one `Done` on its own. A real child `blocked_by` a parent
  sitting in `Backlog` or `Todo` is stuck forever — invisible to every automated run — until a
  human happens to notice and intervene by hand. This actually happened: a 9-ticket feature
  chain sat parked for 16 days because its first child in each branch
  was `blocked_by` a parent that nothing would ever close. File it correctly instead:

  - **The parent records an already-made decision** (the common case — an architecture ticket
    written after every open question was answered): file it directly in **`Done`**. It's a
    reference doc for workers to read, not a gate — closing it at filing time means the first
    real child is never blocked by it.
  - **The parent still holds a genuinely open decision**: file it as an `investigation` (§2) in
    `Todo` so an agent picks it up and closes it — never leave an open decision as a permanent
    blocker with no path to resolution.

  Either way, `blocked_by` between real tickets should chain child-to-child (child N blocks
  child N+1), never child-to-parent. The `parent` field alone is enough for hierarchy and
  context; it needs no relation to gate on.

Batch input (a meeting dump, a list of complaints) → one ticket per independently shippable
change, filed in dependency order so the worker's queue reads top-down.

---

## 5) Report back

List what you filed: `IDENTIFIER-n · priority · one-line`. Flag anything you deliberately did
NOT file and why (already fixed, duplicate, needs a decision you escalated).

Hand off to solo mode (`core/solo/role.md`) to execute.

---

## 6) Filing is not scheduling

A ticket you just wrote goes into the queue at its priority. It does **not** become the next
thing worked, and writing it grants it no head start.

This matters most when this skill is invoked from inside solo mode (`core/solo/role.md`)'s §2.4 — mid-run,
having found an out-of-scope extra. At that moment the new ticket is maximally tempting: the
context is loaded, the cause is already understood, the fix looks like ten minutes. None of
that is a priority signal. Acting on it means the queue order is being set by whatever the
worker happened to trip over, which is precisely the thing a prioritised board exists to
prevent — and the owner finds out only by reading the run afterwards.

So:

- **Set the priority from the defect, not from convenience.** How badly does it hurt a real
  user's day? A one-line fix to a cosmetic issue is still `low`. Do not inflate a follow-up
  to `high` because it is fresh in mind or because you want to justify doing it next.
- **Never file a ticket and then work it in the same run.** Return to the queue and pick by
  priority (`core/solo/role.md` §1, which states this from the other side).
- **Say what you filed and what you are doing next**, so the separation is visible at the
  time rather than reconstructable later.

The one exception is scope, not scheduling: if the extra is genuinely *in* scope for the
ticket already in flight, §2.4 says fold it into that PR rather than filing it at all. Decide
in-scope vs out-of-scope honestly — "in scope" is not a way to smuggle in work you simply
want to do now.
