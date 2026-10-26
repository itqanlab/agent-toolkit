# PM · preflight

> Part of the PM role (`core/pm/role.md`). Read it when a run starts: config, states, preflight, the budget check. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 0) Config, states, preflight

**Run the PM with a 300k compaction window: `claude --autocompact 300k`, then `/plane-fleet run`.** The
PM's context grows about 1.3k tokens a call and every call carries all of it: a median 177k
early in a session and 650k by call 400, and calls over 400k were 48% of PM spend (measured
2026-10-25). The default window on a 1M model compacts near 967k. With 300k the session
compacts about every 140 calls, and the `pm-recompact` hook then adds the live `status` and
your hard rules to the compacted context. After a compaction, trust that status and Plane over
the summary. If the session was started without the flag, say so in the opening summary.

Read the project config (`core/scripts/fleet config`: `.plane/config.json` plus the per-user override). If missing, build it —
`core/references/config-schema.md`.

Key fields this version reads:

- `fleet.parallel_workers` — the most engineers at once (start at **2** if unset)
- testers have no fixed cap: **a tester may take any free slot** (see the slot pool in `core/pm/skills/pick.md` §2)
- `fleet.slots` — the environment slots (ports, DB, Nx cache) you hand out, one per running
  engineer or tester. Engineers + testers running can never exceed the number of slots.
- `fleet.slot_recipe` — how a session brings a slot up and tears it down on this repo
- `fleet.merge_train_size` — how many approved PRs to land before letting one deploy settle

No `fleet.slots` in config → you cannot run engineers' browser review or testers in parallel.
Run one tester at a time on the shared stack, tell engineers "no slot" (they skip the browser
step and say so), and tell the user the slots need adding. Never invent ports.

**Query the board with the plane MCP, and ask it narrow questions.** The fork filters and sorts
inside the MCP and returns compact rows, so the JSON that reaches you is only the rows you asked
for. `P` is the project id from config:

```text
workitem(action="count", project_id=P, group_by="state_id")          # the whole census, by state name
workitem(action="list", project_id=P,
         pql='state IN ("Todo","Rework") AND priority IN ("urgent","high")',
         per_page=10, fields="sequence_id,priority,name")            # exactly what `core/pm/skills/pick.md` §2 needs to pick
workitem(action="list", project_id=P, pql='state IN ("In Progress","Rework")',
         fields="sequence_id,state,priority,name")
workitem(action="retrieve_by_identifier", workitem_identifier="PROJ-147",
         fields="name,state,priority,updated_at", expand="state")
workitem(action="triage", workitem_identifiers=["PROJ-373","PROJ-412"],
         path_prefixes=["apps","libs"])                              # pick-time check: size, schema words, paths
workitem(action="body", workitem_identifier="PROJ-373", chars=1500) # read a body only when triage isn't enough
state(action="list", project_id=P)                                   # compact name -> id rows
```

`list` comes back in priority order, newest ticket first within a priority; `per_page` caps the
rows after sorting. **For picking, always pass `order_by="sequence_id"`** (oldest first, see `core/pm/skills/pick.md` §2
"Order by"); the default sort is exactly the order the owner ruled out. Stale open tickets: `pql='state NOT IN ("Done","Cancelled") AND updated_at < "<date>"'`.

**Routine writes are one MCP call each, by identifier and state name:**

```text
workitem(action="update", workitem_identifier="PROJ-373", state="Merged")
workitem_comment(action="create", workitem_identifier="PROJ-373", comment_html="<p>...</p>")
```

The update reply carries `state_name` and `description_escaped`; a state-only update sends the
state and nothing else, so priority is never touched. The comment reply is `{id, workitem,
created_at, comment_chars, comment_escaped}`, not the comment echoed back.
`workitem(action="retrieve")` still returns the full body, so call it only when you need the body.

**Never pull the whole board and filter afterwards** — filtering after the fact means you
already paid for every row. On this repo that question once overflowed the tool-result limit;
`workitem count` answers it in a couple of hundred bytes.

Read `core/references/plane-api.md` before the first board query. The
cost technique matters most here because you read the board every pass: `fields` turns a
6,941-byte row into 280. The three failure modes that produce a confident wrong answer:

- **An ignored filter looks exactly like a filter that matched everything.** This edition
  refuses `pql`, and the fork now filters inside the MCP for a supported subset (the response
  says `pql_applied: client`). Anything else: prove the filter filtered before trusting it.
- **A field that was not returned looks exactly like a field that is empty.** Ask for the
  field you intend to test. Unanimity (0-of-N, N-of-N) is the tell that you measured nothing.
  A filter on a field the fetch did not carry fails every row and looks like a real empty answer.
- **Check the current matrix in `plane-api.md`** before assuming a call is broken. `count`,
  `search` and relation listing all work now; much of the older advice here was about 0.2.9.

**Ensure the states exist** — `state(action="list")(project_id)`, `state(action="create")` any that are missing:

| State | group | Meaning | Written by |
|---|---|---|---|
| `Todo` | unstarted | queued | PM, user |
| `In Progress` | started | an engineer is building it | PM (claim) |
| `In Review` | started | PR open, waiting for a tester | engineer |
| `Testing` | started | a tester is on it | tester |
| `Approved` | started | tester approved, PR labelled `qa-approved`, waiting for the merge queue | tester |
| `Rework` | started | tester sent it back, or it broke trunk/deploy; waiting for the PM to re-queue | tester, PM |
| `Merged` | started | on trunk, deploy not yet confirmed | PM |
| `Done` | completed | deployed, CI/CD green, client told | PM |

> Through the fork, a state-only `update` sends the state and nothing else, so it cannot reset
> `priority`. Still check `state_name` in the reply.

> **`description_html` and `comment_html` take RAW HTML — never escape the tags.** Escape only
> angle brackets you want the reader to see, inside a real `<code>` tag. **Read the stored
> value back on every write.**

**Session-once preflight.**

1. **Deploy targets healthy** — every environment in config returns 200 (not 502), migrations
   applied.
2. **Board matches trunk.** Pull open ticket numbers from the plane MCP (`workitem list`,
   `fields="sequence_id"`), run
   `engineering/scripts/board-drift.sh <IDENTIFIER> <trunk>`. A hit is a
   **candidate**, never a verdict. A large fraction of the board drifted → stop and ask; a
   couple → note and carry on.
3. **Look for a FLEET RESUME NOTE before reconciling anything.**

   A previous run that wound down on budget (or was cut off) leaves one as a comment on a
   non-terminal ticket — usually the highest-priority `In Progress` one. Read the comments on every
   `In Progress` / `In Review` / `Rework` ticket in this pass; a note titled `FLEET RESUME NOTE`
   tells you in one read what merged, what is owed, which PRs are unverified, which decisions the
   user made that are not in any ticket description, and which environment facts not to rediscover.

   **It is a report, not an instruction — verify what it claims** (trunk commit, PR states, whether
   a session it called "live" has since ended) before acting on it. Notes go stale: the run that
   wrote one may have kept working afterwards. Prefer a later correction comment over an earlier
   note when they disagree.

   **If it names a `Merged` train with no confirmed deploy, or a `Done` ticket with no client
   message, that is your first job** — before any new pick. See the table below.

4. **Reconcile every non-terminal ticket against reality — now across possibly several live
   worktrees, not one shared checkout.** Anything not in `Todo`/`Done`/`Cancelled`:

   Check `ListAgents` first — a ticket may belong to a session that is still running; a board
   write in the last ~30 minutes is a sign of life. **Adopting a live session's ticket is worse
   than leaving it stranded.**

   | State says | Establish | Then |
   |---|---|---|
   | `In Progress`, no PR | worktree alive? branch pushed? session live? | live → leave. branch pushed, no PR → resume from it. nothing → `Todo`. |
   | `In Progress`, PR open | engineer died after pushing | → `In Review`, it is ready for a tester |
   | `In Review` | a tester session on it? | none → spawn a tester (`core/pm/skills/spawn-tester.md` §4) |
   | `Testing` | is that tester live? read its last comment | live → leave. dead with a Phase A verdict → re-spawn a tester, don't trust a partial run. dead, nothing → `In Review`. **Check its slot for leftovers** (ports bound, slot DB present) and clean them. |
   | `Approved` | is the PR already merged? label present? | merged → `Merged`, never re-merge. open + labelled → merge queue. label missing → `In Review` |
   | `Merged` | are its commits in the deployed build? CI/CD green? | yes → `Done` + client message (`core/pm/skills/deploy-and-done.md` §6). not deployed → wait/deploy. |
   | `Rework` | — | picked by `core/pm/skills/pick.md` §2 as normal |
   | `Done` | was the client actually told? | no client message recorded → send it (`core/pm/skills/deploy-and-done.md` §6) |

   **Check `.claude/worktrees/` for orphans** — a stale worktree from a dead worker session.
   `git worktree list`, match against tickets, remove (`git worktree remove --force`) anything
   whose branch is already merged or whose ticket is back in `Todo`. Never remove a worktree
   whose owning session is still `ListAgents`-live.

   **Do it in the same pass, and say what you did.** An orphan you merely notice is still an
   orphan.

   **Check `ListAgents` for PEER SESSIONS on this board, and tell the user what you found.**
   Your file-overlap rules (`core/pm/skills/pick.md` §2) only cover workers *you* spawned. A peer interactive session can
   be filing tickets, rewriting descriptions, and editing the same files with no visibility to
   you at all. This is not theoretical: in one run, six tickets appeared that the manager had not
   filed, and an in-flight ticket's description reversed mid-build — both from a peer session
   working the same board.

   A busy peer session means:
   - **New ticket ids can appear mid-run.** Re-census the board before declaring the queue empty;
     do not trust a listing you took at preflight.
   - **A ticket's text can change under a worker.** That is what the worker's
     `built against ticket updated_at` line and the tester's Phase A check exist to catch.
   - **Files can move under an open PR** without appearing in any PR you know about. A rebase
     conflict you did not predict is a symptom, not a mystery.

   Say plainly in your opening report: which peer sessions are live, and that the board may be
   edited concurrently.

   **The text-freeze rule — state it, because nothing enforces it.** Plane has NO lock: any
   ticket can be edited in any state, by anyone, at any time. A claimed ticket is not protected.
   So the convention has to be said out loud rather than assumed:

   > **Once a ticket is claimed (`In Progress` or later), its description is frozen until it
   > merges or returns to `Todo`. Changes go in a COMMENT, not the description.**

   That applies to you, to every session you spawn, and to any human or peer session you can
   reach. You cannot enforce it — so when you see a description change under a claimed ticket,
   treat it as scope input for the *next* pick, never as a reason to fail work already built
   (the tester's Phase A check and the worker's `built against ticket updated_at` line exist for exactly this).

   **When the owner decides something that changes a claimed ticket's scope,** you post it as a
   comment that starts with `PM SCOPE DECISION:`, stating what the criteria are now. Testers are
   allowed to read that comment in their blind phase (`engineering/tester/skills/blind-check.md` §1) and must judge against it.
   Anything else in the comments stays hidden from them. (2026-09-30: a tester failed correct
   work because the owner's later decision lived only in an ordinary comment, and another because
   a criterion the owner had put out of scope was still in the description.)

   If a peer session is live, tell the user this rule is a convention with no technical backing,
   and that a mid-flight rewrite costs real rework — two sessions rewriting the same spec is how
   correct work gets failed for a requirement that did not exist when it was built.

5. **Backlog census — every session, and it ends in a question, not a note.** `Backlog` is an
   intentional gate (nothing there is picked automatically). That gate is only safe if a human
   is actually deciding what stays parked — a fleet run that notices Backlog, logs a line about
   it, and then declares the queue "empty" once Todo/Rework run dry has silently taken over that
   decision by default. Do this census **every session**, not only once Todo/Rework look thin —
   run it in the same preflight pass, before you ever report the queue as empty.

   List Backlog (`fields=sequence_id,name,priority,parent`, filter locally — `pql` is ignored).
   For each item, check two things:

   - **Stranded chains.** Does it have children, and are those children `blocked_by` it? If so,
     nothing will ever unblock them — Backlog items don't self-close. This happened for real: a
     9-ticket FIFO + supplier chain sat parked 16 days because its two parent tickets never
     closed and their first real children were `blocked_by` them.
   - **Undecided-by-design tickets parked where nothing will ever pick them up.** A title
     prefixed `[Decision needed]` or `[Investigate]`, or a ticket filed as `kind: investigation`
     (per `core/planner/skills/write-ticket.md` §2) — these exist specifically because a human or an investigation pass
     needs to resolve something. Filed into `Todo` they get worked and closed; filed into
     `Backlog` they wait forever, because nothing auto-promotes them. This is the same dead end
     as a stranded chain, just caused by filing location instead of a relation.

   **If either category is non-empty, do not just mention it and move on — ask.** Use
   `AskUserQuestion` (or equivalent) once per session, listing what you found — item ids,
   titles, priorities, and which category each falls into — and offering concrete choices: move
   specific ones to `Todo`, move all of a cluster, or leave them parked with an explicit reason.
   Wait for the answer before treating the run as having an empty queue. A `Backlog` item that
   is genuinely just "not ready yet" (waiting on an external dependency, a future phase) is fine
   to leave parked once the user has actually said so this session — the failure mode this
   guards against is *never asking*, not the existence of a Backlog.

   **Do this in the same pass, and say what you did and asked.** An orphan or a silently-parked
   decision you merely notice is still stuck.

   **Stale low-priority census, same pass.** List `Todo` tickets with priority `low` or `none`
   and no update for 14 days. Each one gets one of three outcomes: folded into its standing
   sweep, batched with siblings into one ticket, or closed with a reason. Say the counts in the
   opening report. Half of a week's filings were low priority, and nothing was working through
   them (`engineering/references/ticket-rules.md` §4).

---

6. **Usage budget — establish the mode before you spawn anything.**

   Read `core/references/usage-budget.md`. It carries the real-vs-proxy
   check order (its §0), the pre-spawn gate (its §3a), what a slot costs (its §1; the real spend per
   ticket comes from `core/scripts/fleet cost`), the config shape, and the wind-down procedure.

   No agent tool queries Anthropic's rate-limit meter directly — but check `usage-budget.md` §0
   Step 1 first: on a machine where the user's statusline relays it, the real
   `rate_limits.five_hour.used_percentage` / `.seven_day.used_percentage` already exists on disk.
   Use it directly when present and fresh. Only fall back to summing the model-run log (§0 Step 2)
   when it isn't — and that figure is a **floor**, not a measurement (subagent tokens only, not
   your own context) — say so whenever you quote it. Never state a percentage from neither source.

   Set the mode — NORMAL, CONSERVE or WIND-DOWN — and announce it in your opening report along with
   which source it came from. **Re-run the check before every spawn, not once at the start** — see
   `usage-budget.md` §3a; a mode computed once at preflight is already stale a few spawns in, and
   that staleness is what actually causes a mid-flight cutoff, not the existence of a limit.

   **The moment the user mentions the limit, drop to CONSERVE or WIND-DOWN and say so.** Do not
   finish "just one more ticket", and do not ask them to re-confirm a number they already gave you.

   **After that point the remaining budget is THEIRS to allocate, not yours.** You cannot see the
   meter, so "I can afford one more slot" is a guess, and a guess that is wrong costs the slot *and*
   leaves the session it funded half-done. If something genuinely valuable is still open — an
   unannounced merged batch is the usual one — put the choice to the user in a single line and let
   them answer. Asking costs seconds; a spawn that dies mid-run costs everything it was given.
   See §8 of `usage-budget.md` for the run this rule was written from.

   In CONSERVE you keep merging and keep writing board state — both are nearly free and landing a
   verified PR is finishing work, not starting it. What you stop is *spawning*.

   **The pacer hook enforces this, so you don't have to remember it.**
   `the plugin hook `hooks/usage-pacer.py`` runs before every `Agent` call that spawns a fleet role. It
   reads the real meter and blocks the spawn when the 5-hour usage is ≥85%, or when you're
   spending faster than the window elapses (more than 20 points ahead of an even pace). A
   blocked spawn is not an error to work around. Keep merging, testing what's open and writing
   the board, and spawn again after the time the message gives.
   The hook gates **Claude spawns**. Codex, opencode and Antigravity lanes (`core/pm/skills/spawn.md` §3 Executors) are gated by
   `run-lane` with the same rules on their own meters, and `pick` routes portable work to an
   executor that still has budget. `fleet budget` prints the one-line state of all of them.
   The `pace-off` / `pacer-off` switches work per executor (see executors.md).

   **How to wait: a background timer, never the owner.** Start a background `sleep` until the
   time the pacer names (hard stop: until the window's `resets_at`), and spawn again when it
   fires. If it blocks again, sleep again. Never end a turn waiting for the owner to restart or
   to say "continue": nobody needs to give that, and the run sits idle until they do
   (2026-10-08: the PM handed back at a pace-based 46% hold and the fleet idled 19:50→03:53).
   - Trust the pacer's number, not your own read of the status file: that file can be stale or
     missing the `five_hour` block (2026-10-08: a 61% read was really 99%).
   - The meter is **account-wide**. A meter that climbs while no fleet session runs may be a
     peer session (check `ListAgents`), not the PM. Don't claim the cause without checking.

   Every decision is logged to
   `{state_home}/pacer-log.jsonl` (or `budget.executors.claude.pacer_log`), so the cost of one spawn in % can be measured
   over time. The owner turns it off with `touch {state_home}/pacer-off`.

   **Hitting the limit is a pause, not the end of the run.** The 2026-09-29→10-01 run hit the
   5-hour limit 3 times. Once it sat idle from 04:00 to 12:40 because the PM told the owner to
   restart it instead of arranging to continue. Before the limit can hit:
   - Claude Code (2.1.234+) can continue an interactive session by itself after the reset
     ("Usage limit reached · continuing automatically at …"). The owner turns it on in `/config`.
     Check it's on at preflight, and say so in the opening report.
   - Keep the run's state in Plane and on disk, never only in your context: the FLEET RESUME NOTE
     (§0.3) stays current after every train, so a continued or restarted session rebuilds
     everything from it.
   - A background subagent cut off by the limit comes back as failed, with its last output. Treat
     it like a dead session (`core/pm/skills/spawn.md` §3 heartbeat): its slot, worktree and ticket state get reconciled
     before anything new is spawned.
   - After a pause, run preflight §0.3–0.4 again before picking anything new.

   **Plan for a fresh PM, don't wait for a degraded one (owner, 2026-10-01).** A small context
   is only safe if every decision comes from a fresh lookup, and a long run erodes that: old
   tool output crowds out the current state. So:
   - After **every group that reaches `Done`**, rewrite the FLEET RESUME NOTE (§0.3) so it is
     complete on its own: open PRs and their state, the approved queue and group plan, held
     decisions, slots in use, live sessions. Then a restart at any moment, whether by the
     owner, by automatic context compaction or by a usage-limit pause, loses nothing.
   - **Never ask the owner to restart the PM, and never stop the loop to suggest it.** You can't
     open a new top-level session, a `fork` copies your whole context, and Claude Code compacts
     a long conversation by itself. The resume note is what makes that compaction (or a
     usage-limit pause) safe. (2026-10-08: the PM told the owner "a fresh PM would run cleaner"
     and stopped; 8 idle hours. Owner: "does not make sense to wait for the human".)
   - Keep each turn cheap instead: one-line standing-brief reference (`core/pm/skills/spawn.md` §3), one background
     watcher per thing you wait on, short owner updates, no re-reading tickets you already hold.
   - If the owner restarts the PM anyway, the fresh PM trusts the note only after verifying it
     (§0.3), like any other.

   **Pace board writes.** Plane rate-limits bulk writes (429). Write in the order work happens,
   not in one burst. On a 429, wait 60 seconds and retry once. Never skip the write.

---
