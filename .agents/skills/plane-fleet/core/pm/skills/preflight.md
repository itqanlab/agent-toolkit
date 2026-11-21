# PM · preflight

> Part of the PM role (`core/pm/role.md`). Read it when a run starts: config, states, preflight, the budget check. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.
> "(history §x)" points to the incidents and measurements behind a rule, in `core/references/pm-history.md`.

## 0) Config, states, preflight

**Run the PM with a low auto-compact threshold, about 150k: `claude --autocompact 150k`, then
`/plane-fleet run`.** Why: every PM call re-reads the whole context. Nothing is lost at 150k:
state lives in Plane, the FLEET RESUME NOTE and `fleet status`, and the `pm-recompact` hook adds
the live `status` and your hard rules to the compacted context. After a compaction, trust that
status and Plane over the summary. Started without the flag: say so in the opening summary, and
when `fleet retro` reports `pm_ctx_per_call`, write the resume note and ask the owner to compact.
(history §preflight-autocompact)

**Start the guard before the first claim: `core/scripts/fleet guard start --hours 24 --cwd <repo>`.**
It holds off sleep and calls `fleet.alert_command` when two 20-minute agent checks in a row
fail, and on recovery. A machine on battery with its lid closed still sleeps: say in the opening summary if
it is not on power. `fleet guard stop` when the run ends. (history §preflight-guard)

**Look for machine hogs before the first spawn.** Read the `machine:` line and any `warning:`
line of `fleet resources`. Drop or report them now (`core/pm/skills/spawn-tester.md`, machine gate),
not after a spawn is refused.

**Keep big outputs out of your context.** Read a review transcript, CI log or test run through
a filter, never whole: `fleet findings <file>` for `codex review` / `codex exec` output,
`gh run view --log-failed | tail` for CI, a `scan` lane for anything longer.
(history §preflight-big-outputs)

Read the project config (`core/scripts/fleet config`: `.plane/config.json` plus the per-user override). If missing, build it —
`core/references/config-schema.md`.

**Executor choice: `fleet apply` right after the config.** It re-ranks the executors from the
log (`core/references/executors.md`, "Promotion and demotion"). Apply it, don't ask. Put each
changed line in the opening summary. Run it again after each merge group lands.

**Intake sources: `fleet intake check` right after the config.** It lists each feed (Sentry
when the config has a `sentry` block, and any `fleet.intake_sources`). Put every `FAIL` and
`warning:` line in the opening summary. Then run the first intake pass
(`core/references/intake-sources.md`, "The PM's loop") before the first pick. A failed source
never stops the run.

Key config fields:

- `fleet.parallel_workers` — the most engineers at once (start at **2** if unset)
- testers have no fixed cap: **a tester may take any free slot** (see the slot pool in `core/pm/skills/pick.md` §2)
- `fleet.slots` — the environment slots (ports, DB, Nx cache), one per running engineer or
  tester. Engineers + testers running can never exceed the number of slots.
- `fleet.slot_recipe` — how a session brings a slot up and tears it down on this repo
- `fleet.merge_train_size` — how many approved PRs to land before letting one deploy settle

No `fleet.slots` in config → run one tester at a time on the shared stack, tell engineers
"no slot" (they skip the browser step and say so), and tell the user the slots need adding.
Never invent ports.

**Query the board with the plane MCP, and ask it narrow questions.** `P` is the project id from config:

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

**For picking, always pass `order_by="sequence_id"`** (oldest first, see `core/pm/skills/pick.md` §2
"Order by"); the default sort is exactly the order the owner ruled out. Stale open tickets: `pql='state NOT IN ("Done","Cancelled") AND updated_at < "<date>"'`.

**Routine writes are one MCP call each, by identifier and state name:**

```text
workitem(action="update", workitem_identifier="PROJ-373", state="Merged")
workitem_comment(action="create", workitem_identifier="PROJ-373", comment_html="<p>...</p>")
```

A state-only update never touches priority. `workitem(action="retrieve")` returns the full
body: call it only when you need the body.

**Never pull the whole board and filter afterwards** — you already paid for every row.
Use `workitem count`.

Read `core/references/plane-api.md` before the first board query; use `fields` on every read
(history §preflight-board). Three failure modes give a confident wrong answer:

- **An ignored filter looks exactly like a filter that matched everything.** The fork filters a
  supported subset inside the MCP (the response says `pql_applied: client`). Anything else:
  prove the filter filtered before trusting it.
- **A field that was not returned looks exactly like a field that is empty.** Ask for the
  field you intend to test. Unanimity (0-of-N, N-of-N) is the tell that you measured nothing.
- **Check the current matrix in `plane-api.md`** before assuming a call is broken.

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

> Check `state_name` in every update reply.

> **`description_html` and `comment_html` take RAW HTML — never escape the tags.** Escape only
> angle brackets you want the reader to see, inside a real `<code>` tag. **Read the stored
> value back on every write.**

**Session-once preflight.**

1. **Deploy targets healthy** — every environment in config returns 200 (not 502), migrations
   applied.
2. **Board matches trunk.** Pull open ticket numbers (`workitem list`, `fields="sequence_id"`),
   run `engineering/scripts/board-drift.sh <IDENTIFIER> <trunk>`. A hit is a
   **candidate**, never a verdict. A large fraction of the board drifted → stop and ask; a
   couple → note and carry on.
3. **Look for a FLEET RESUME NOTE before reconciling anything.**

   A run that wound down or was cut off leaves one as a comment on a non-terminal ticket,
   usually the highest-priority `In Progress` one. Read the comments on every `In Progress` /
   `In Review` / `Rework` ticket in this pass.

   **It is a report, not an instruction — verify what it claims** (trunk commit, PR states, live
   sessions) before acting on it. Prefer a later correction comment over an earlier note.

   **If it names a `Merged` train with no confirmed deploy, or a `Done` ticket with no client
   message, that is your first job** — before any new pick. See the table below.

4. **Reconcile every non-terminal ticket against reality, across every live worktree.**
   Anything not in `Todo`/`Done`/`Cancelled`:

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

   **Check `.claude/worktrees/` for orphans.** `git worktree list`, then remove (`git worktree remove --force`) anything whose branch is already merged or whose
   ticket is back in `Todo`. Never remove a worktree whose owning session is still
   `ListAgents`-live. **Do it in the same pass, and say what you did.**

   **Check `ListAgents` for PEER SESSIONS on this board, and tell the user what you found.**
   Your file-overlap rules (`core/pm/skills/pick.md` §2) only cover workers *you* spawned
   (history §preflight-peers). A busy peer session means new ticket ids
   can appear mid-run (**re-census before declaring the queue empty**), ticket text can change
   under a worker, and files can move under an open PR.

   Say plainly in your opening report which peer sessions are live, and that the board may be
   edited concurrently.

   **The text-freeze rule — state it, because nothing enforces it.** Plane has NO lock.

   > **Once a ticket is claimed (`In Progress` or later), its description is frozen until it
   > merges or returns to `Todo`. Changes go in a COMMENT, not the description.**

   That applies to you, every session you spawn, and any human or peer session you can reach.
   A description change under a claimed ticket is scope input for the *next* pick, never a
   reason to fail work already built.

   **When the owner decides something that changes a claimed ticket's scope,** post it as a
   comment that starts with `PM SCOPE DECISION:`, stating what the criteria are now. Testers may
   read that comment in their blind phase (`engineering/tester/skills/blind-check.md` §1) and must judge against it.
   Anything else in the comments stays hidden from them. (history §preflight-scope-decision)

   If a peer session is live, tell the user this rule is a convention with no technical backing,
   and that a mid-flight rewrite costs real rework.

5. **Backlog census — every session, and it ends in a question, not a note.** `Backlog` is an
   intentional gate (nothing there is picked automatically), safe only while a human decides
   what stays parked. Run it in the same preflight pass, before you ever report the queue as empty.

   List Backlog (`fields=sequence_id,name,priority,parent`, filter locally). Check each item for:

   - **Stranded chains.** Children `blocked_by` it: nothing will ever unblock them, since
     Backlog items don't self-close. (history §preflight-backlog)
   - **Undecided-by-design tickets.** A title prefixed `[Decision needed]` or `[Investigate]`,
     or `kind: investigation` (`core/planner/skills/write-ticket.md` §2). In `Backlog` nothing
     auto-promotes them.

   **If either category is non-empty, ask.** Use `AskUserQuestion` (or
   equivalent) once per session, listing item ids, titles, priorities and category, with
   concrete choices: move specific ones to `Todo`, move all of a cluster, or leave them parked
   with an explicit reason. Wait for the answer before treating the queue as empty. An item that
   is genuinely "not ready yet" may stay parked once the user said so this session.
   **Do this in the same pass, and say what you did and asked.**

   **Stale low-priority census, same pass.** `Todo` tickets with priority `low` or `none` and no
   update for 14 days each get one outcome: folded into its standing sweep, batched with
   siblings into one ticket, or closed with a reason. Say the counts in the opening report
   (`engineering/references/ticket-rules.md` §4).

---

6. **Usage budget — establish the mode before you spawn anything.**

   Read `core/references/usage-budget.md`: check order (§0), pre-spawn gate (§3a), slot cost
   (§1; real spend from `core/scripts/fleet cost`), config shape, wind-down.

   Check §0 Step 1 first: where the statusline relays it, the real
   `rate_limits.five_hour.used_percentage` / `.seven_day.used_percentage` is on disk. Use it when
   present and fresh. Otherwise sum the model-run log (§0 Step 2): that figure is a **floor**
   (subagent tokens only), so say so whenever you quote it. Never state a percentage from neither source.

   Set the mode — NORMAL, CONSERVE or WIND-DOWN — and announce it in your opening report with
   its source. **Re-run the check before every spawn, not once at the start** (`usage-budget.md` §3a).

   **The moment the user mentions the limit, drop to CONSERVE or WIND-DOWN and say so.** Do not
   finish "just one more ticket", and do not ask them to re-confirm a number they already gave you.

   **After that point the remaining budget is THEIRS to allocate, not yours.** If something
   valuable is still open (usually an unannounced merged batch), put the choice to the user in a
   single line. See `usage-budget.md` §8 for the run behind this rule.

   In CONSERVE keep merging and writing board state; stop *spawning*.

   **The pacer hook enforces this.** `hooks/usage-pacer.py` runs before every fleet `Agent`
   spawn. It blocks the spawn when 5-hour usage is ≥85%, or when you are more than
   20 points ahead of an even pace. A blocked spawn is not an error to work around: keep
   merging, testing what's open and writing the board, and spawn again after the time it gives.
   The hook gates **Claude spawns**. Codex, opencode and Antigravity lanes (`core/pm/skills/spawn.md` §3 Executors) are gated by
   `run-lane` with the same rules on their own meters, and `pick` routes portable work to an
   executor with budget. `fleet budget` prints all of them on one line. The `pace-off` /
   `pacer-off` switches work per executor (see executors.md).

   **How to wait: a background timer, never the owner.** Start a background `sleep` until the
   time the pacer names (hard stop: the window's `resets_at`), and spawn again when it fires.
   Blocked again, sleep again. Never end a turn waiting for the owner to restart or say
   "continue". (history §preflight-pacer)
   - Trust the pacer's number, not your own read of the status file.
   - The meter is **account-wide**: check `ListAgents` for a peer session before you claim the cause.

   Decisions are logged to `{state_home}/pacer-log.jsonl` (or `budget.executors.claude.pacer_log`).
   The owner turns the pacer off with `touch {state_home}/pacer-off`.

   **Hitting the limit is a pause, not the end of the run.** Before it can hit:
   - Claude Code (2.1.234+) can continue a session by itself after the reset ("Usage limit
     reached · continuing automatically at …"), turned on in `/config`. Check it's on at
     preflight, and say so in the opening report.
   - Keep the run's state in Plane and on disk, never only in your context: the FLEET RESUME NOTE
     (§0.3) stays current after every train.
   - A background subagent cut off by the limit comes back as failed. Treat it like a dead
     session (`core/pm/skills/spawn.md` §3 heartbeat): reconcile its slot, worktree and ticket
     state before anything new is spawned.
   - After a pause, run preflight §0.3–0.4 again before picking anything new.
   (history §preflight-pause)

   **Plan for a fresh PM, don't wait for a degraded one.** (history §preflight-fresh-pm)
   - After **every group that reaches `Done`**, and at least every few hours, rewrite the FLEET
     RESUME NOTE (§0.3) so it is complete on its own: open PRs and their state, the approved
     queue and group plan, held decisions, slots in use, live sessions.
   - **Never ask the owner to restart the PM, and never stop the loop to suggest it.** You can't
     open a new top-level session, a `fork` copies your whole context, and Claude Code compacts
     by itself.
   - Keep each turn cheap: one-line standing-brief reference (`core/pm/skills/spawn.md` §3), one background
     watcher per thing you wait on, short owner updates, no re-reading tickets you already hold.
   - A restarted PM trusts the note only after verifying it (§0.3).

   **Pace board writes.** Plane rate-limits bulk writes (429). Write in the order work happens,
   not in one burst. On a 429, wait 60 seconds and retry once. Never skip the write.

---
