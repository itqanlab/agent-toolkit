# Usage budget — spend the 5-hour window deliberately, and stop safely before it ends

Every Plane skill that spawns sessions or runs a loop reads this. It exists because a run that
hits the usage limit mid-flight does not stop cleanly — it stops *wherever it was*, which is how
you get an orphaned verify database, a ticket sitting `In Progress` with nobody on it, and a PR
merged whose board row still says `In Review`.

**The goal is not to use less. It is to never be surprised.**

---

## 0) What you can and cannot know — read this before trusting any number

**No agent tool queries Anthropic's rate-limit meter directly.** But on a machine where the user's
statusline is configured to relay it, the *real* number already exists on disk — check for it
FIRST, before falling back to the token-count proxy below.

**Step 1 — look for the real number.** Check the status file named in `budget.executors.claude.status_file` (only
present if the user has a statusline relay capturing the harness's own statusLine JSON payload,
which carries a `rate_limits` block straight from Anthropic). If it exists:

```bash
python3 -c "
import json
d = json.load(open('<status_file>'))
print(d.get('session_id'), d.get('rate_limits'))
"
```

Read `rate_limits.five_hour.used_percentage` and `rate_limits.seven_day.used_percentage` plus
their `resets_at` epoch timestamps. **This is a measurement, not an estimate** — use it directly,
and say plainly where it came from. Sanity-check freshness: if the file's `session_id` is from a
much older/unrelated session or looks stale, don't trust it — fall through to Step 2.

This file is a side effect of one user's personal statusline customization, not a stable Claude
Code feature — it will not exist on other machines or for other users of this skill. Never assume
it is there; always check.

**Step 2 — fall back to the token-count floor, and say plainly it's a proxy.** If the real file is
missing or stale, the only thing left is your own spend, because you already log it. Every `Agent`
you spawn returns `tokens`, and the outcomes log (`{state_home}/executor-outcomes.jsonl`)
records it per row. Sum today's rows and you have a figure.

```bash
jq -s 'map(select(.ts >= "<today>")) | {runs: length, subagent_tokens: (map(.tokens)|add)}' \
  {state_home}/executor-outcomes.jsonl
```

**That figure is a FLOOR, not a total, and it can be flatly wrong, not just imprecise** — it
buckets spend by calendar day rather than the actual rolling 5-hour window, so a burst from an
already-reset window still counts against you. It also excludes the manager's own context, every
tool result the manager read, and the re-sent conversation on each turn. Never present it as
equivalent to Step 1's number; say which one you're using.

**Do not claim a percentage from neither source.** If Step 1's file doesn't exist and you're
relying on Step 2, do not imply you can see the real meter.

**The user is the authority.** When they say how much is left, that overrides either estimate
here.

---

## 1) Measured costs — real numbers, so estimates are not invented

From one full `/team-pm` run on the CRM repo, 2026-09-05 (15 logged subagent runs,
**3.53M subagent tokens**):

| role | model | tokens per session |
|---|---|---|
| pre-merge verify | opus | 222k – 272k (**~250k**) |
| worker, ordinary ticket | sonnet / opus | 199k – 254k (**~235k**) |
| worker, rework | opus | ~240k |
| bookkeeping / census | haiku | ~123k |

**The planning number: one parallel slot costs roughly a quarter of a million tokens.**

So a fleet round of 2 workers + 3 verify slots is **~1.25M tokens** before the manager's own
overhead. Two such rounds is most of a window. This is why "just spawn more agents" is not free
throughput, and a single CI runner is often the real bottleneck.

---

## 2) Config

Add to `.plane/config.json`. All optional; the defaults below apply when absent.

```json
"budget": {
  "session_token_budget": 5000000,
  "reserve_fraction": 0.20,
  "cost_per_slot": 250000,
  "wind_down_on_user_signal": true
}
```

- `session_token_budget` — the spend you are willing to reach in one window. Not a real limit; a
  self-imposed one.
- `reserve_fraction` — the tail you refuse to spend on new work. This is what pays for winding
  down: landing verified PRs, writing board state, tearing down slots, reporting. **0.20 of a 5M
  budget is 1M — about four slots, which is roughly what a clean wind-down costs.** Do not shrink
  it below 0.15.
- `cost_per_slot` — used for the pre-spawn check. Raise it if your measured rows are bigger.

---

## 3) Three modes. Announce the mode whenever it changes.

**If §0 Step 1 gave you a real `rate_limits.five_hour.used_percentage`, use that directly** —
NORMAL below 80%, CONSERVE from 80–95%, WIND-DOWN above 95% or once `resets_at` is imminent. State
it as the real percentage it is, not translated into a fake token figure.

Otherwise, compute `spent` from the run log (§0 Step 2), `budget` and `reserve` from config.

### NORMAL — `spent < budget - reserve`
Run as designed. Fill worker and verify slots.

### CONSERVE — within one slot's cost of the reserve, i.e. `spent + cost_per_slot >= budget - reserve`
The line that matters: **finish what is running, land what is verified, start nothing new.**

- Do **not** spawn workers. Do **not** spawn verify sessions.
- **Keep merging.** A merge costs the manager a handful of tool calls and no subagent tokens, and
  landing a verified PR is finishing work, not starting it. Leaving verified PRs open across a
  multi-hour gap just earns you rebase conflicts later.
- Keep writing board state. It is nearly free and it is what makes resume possible.
- Prefer `haiku` for any remaining bookkeeping.

### WIND-DOWN — the user says to stop, or you judge the window is nearly gone
Run §4 immediately.

**Enter CONSERVE or WIND-DOWN the moment the user mentions the limit.** Do not argue, do not
finish "just one more ticket", and do not ask them to confirm a number they already gave you.

---

## 3a) The pre-spawn gate — this is what actually prevents a mid-flight stop

A run does not die from running out of budget in the abstract. It dies because it spawned **one
more agent than the window had room for**, and that agent got cut off mid-task. The fix is
mechanical, not judgment-based: **re-run §0's check immediately before every single `Agent()`
call**, not once at the start of the session. A mode computed at preflight is already stale by the
third spawn.

Before each spawn:

1. Re-read §0 Step 1 (the real `rate_limits` file) fresh — do not reuse a value from earlier in
   this same run. It is cheap (one file read) and the whole point is that it can change.
2. If `five_hour.used_percentage` has crossed into CONSERVE or WIND-DOWN territory since your last
   check, stop spawning **now**, even if you were mid-way through filling planned slots this round.
   A round you "were already committed to" is not an exception.
3. If you're in WIND-DOWN and `resets_at` is known: this is not just a stop signal, it's a
   **resume time**. Run §4 (below), then use `ScheduleWakeup` (or tell the user the exact
   `resets_at` time) so work picks back up automatically instead of waiting on someone to notice
   and re-invoke the skill. Preventing a "sudden stop" includes making the restart automatic, not
   only making the stop clean.
4. If only the Step 2 token-count fallback is available (no real file), the same rule applies:
   re-sum the log before each spawn, not once. It's a worse number, but it is only useless if it's
   stale.

**This replaces "check the mode once in preflight and proceed."** That pattern is exactly how the
2026-09-05 failure happened — the mode was computed once, then a plan was executed against it while
the real number kept moving underneath.

---

## 4) The wind-down procedure — safe to enter at ANY point

### 4.1 Never kill a running session to save budget

This is the rule people get wrong. A `/team-tester` (tester) or `/team-engineer` (engineer)
session holds a **slot: its own database, ports and a git worktree** (plus a Redis container or
bucket on repos that have them), and its teardown is the last
thing it does. Kill it and every one of those leaks — and the next session that is assigned that
slot must stop and report an occupied slot, which costs more than letting the first one finish.

**Let running sessions finish.** They are already paid for. Their remaining cost is small compared
to the mess they leave if interrupted. The only thing you stop is *starting new ones*.

### 4.2 Land what is already verified

For each PR that is verified PASS and green: merge it, reset trunk, write the ticket to `Merged`
**immediately after its own merge**. The window between "on trunk" and "board says so" is exactly
the window a stopped session makes the board lie in.

Do not start a merge you cannot finish writing up. If CI is still running on a PR, leave it — a
verified PR with green CI next session is a better state than a half-recorded merge.

### 4.3 Leave no ticket claimed with nobody on it

Any ticket `In Progress` whose session has ended and which has no pushed branch goes back to
`Todo`. A claimed ticket with no live session and no branch is the single most confusing state to
resume into, because the next session cannot tell whether work exists.

If a branch or PR exists, leave it `In Progress` and say so in the handoff — that is recoverable.

### 4.4 Write the resume note — on the board, not only in chat

Post one comment on the highest-numbered active ticket, or on the ticket most representative of
the run, containing:

- trunk commit at wind-down
- what merged this session, by ticket id
- what is verified and queued to land, with PR numbers
- **what is owed** — above all, any train sitting in `Merged` whose deploy/CI-CD is not yet
  confirmed and therefore has NOT been set `Done` or notified to the client
- any sequencing constraint a fresh session would not rediscover (ordered pairs, `blocked_by`)
- any decision the user made this session that is not yet encoded in a ticket description

Chat scrollback does not survive. The board does.

### 4.5 Check for orphans before you stop

```bash
git worktree list
docker ps -a --format '{{.Names}}' | grep -i verify
psql -lqt | cut -d'|' -f1 | grep -i verify
```

Anything belonging to a session that has ended: remove it. Anything belonging to a session still
running: leave it and name it in the resume note so the next session does not "clean up" a live
slot.

---

## 5) Client notification is NOT part of wind-down

Only `/team-pm` messages the client, and only as it sets a ticket `Done` after the deploy
and CI/CD are confirmed green.

**Never send a "here's what we did today" summary to be helpful.** Merged is not deployed, and
deployed is not confirmed. Describing unconfirmed work to the client is the failure this rule
exists to prevent.

**But do NOT read that as "defer the notification to next session."** That mistake was made on
2026-09-05: nine tickets sat live on dev, unannounced, and the manager recommended waiting two
hours for the window to reset. The user pushed back and was right.

The reasoning that was wrong: "notify the client" and "prove it works" are not in conflict, and
deferring is not the safe middle. **A post-deploy verify is ONE slot (~250k).** If a merged batch
is live and unannounced, spend that slot — it verifies *and* notifies, which is both faster and
more honest than waiting. Reserve budget exists to finish exactly this kind of loop.

So, when winding down with an unverified merged batch, the notification is the **highest-value
thing left in the window** — it closes the client loop and moves real tickets to `Done`.

**But you do not get to decide unilaterally that you can afford it.** See §8 — once the user has
said the window is nearly gone, the remaining budget is theirs to allocate, not yours. Put the
choice to them in one line and let them answer:

> Nine tickets are live on dev and unannounced. Closing that needs one post-deploy verify
> (~250k, one slot). You said we're near the limit — do you want me to spend it now, or first
> thing after the reset?

That takes seconds, costs almost nothing, and is the difference between the loop closing and a
session dying halfway through it.

---

## 8) Who decides how the last of the window is spent — and the mistake that put this section here

**Once the user has told you the window is nearly gone, the remaining budget is theirs to
allocate.** Not yours to re-litigate, however valuable the work looks to you.

This is not caution for its own sake. It follows from §0: **you cannot see the meter.** An
"is this affordable?" judgment has no data behind it. You are guessing, and a guess that is wrong
does not cost you one slot — it costs the slot *and* leaves whatever the session was doing
half-done.

**A spawn that dies mid-run is strictly worse than a spawn you never made.** It burns the tokens,
returns nothing, and can leave a partial slot behind — a created database, an un-torn-down
container, a ticket moved but not commented. So as the window closes, the bar for spawning goes
**up**, not down. "This is important" is a reason to *ask*, never a reason to assume.

### The failure this is written from (2026-09-05)

The user said the 5-hour window was ~90% gone and to finish only what was running. Later, pressing
a separate point, they said *"we must notify the client, that is it."* That was a statement about
how the system should behave. It was read as a work order, and a 250k post-deploy verify was
spawned at roughly 95% of the window. **It died mid-run on the session limit**, having done
nothing, minutes after the same session had written a document about not being surprised by that
limit.

Two distinct errors, both worth naming because they look different from the inside:

1. **Spending budget the user had already said was nearly gone**, on a unilateral call, with no
   ability to measure whether it fit.
2. **Treating a conversation about the mechanism as an instruction to run the mechanism.** When the
   user is discussing how the skill should behave — "can the skills handle this", "we must always
   X", "why does it do Y" — the deliverable is **the changed behaviour encoded in the skill**, not
   a demonstration of it. Fix the rule, show them the rule, and ask before acting on it. If they
   wanted it done right now they will say so, and then it is a work order.

**The tell for the second one:** you are about to spawn something, and the user's last message
contained no ticket, no target, and no "now". If a message would be fully answered by an edit to a
skill file, answer it with an edit to a skill file.

**Weigh the cost properly.** A deployed-but-unannounced batch is worse than an undeployed one: the
client sees changes they cannot explain, and any half-finished flow among them looks like a defect
rather than work in progress. The client's view of the project *is* the messages they receive.
Being slow to tell them is a real cost, not a safe default.

---

## 6) Resuming after the window resets

The existing preflight reconciliation already handles most of this — run it as written. Two
additions:

1. **Read the resume note first** (§4.4). It tells you what is owed in one read instead of
   reconstructing it from the board.
2. **Post-deploy verify the outstanding `Merged` batch before picking any new ticket.** It is the
   oldest owed work, it is what the client is waiting on, and it is cheap compared with a fresh
   build. Finishing the last run beats starting the next one.

---

## 7) What to tell the user

State the mode, the measured floor, and what it excludes. One or two lines:

> Entering CONSERVE — ~3.5M subagent tokens logged this session (a floor; excludes my own
> context). Finishing the three running sessions and landing what is verified, starting nothing
> new. Owed after this: post-deploy verify for 7 merged tickets, and the client notification that
> goes with it.

Never present an estimate as a measurement, and never imply you can see the usage meter.
