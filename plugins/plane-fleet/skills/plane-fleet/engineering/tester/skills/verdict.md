# tester · verdict

> Part of the tester role (`engineering/tester/role.md`). Read it when both phases are done: approve or send to Rework, tear down, report. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 3) Outcome — approve or rework, then report to the manager

You decide **approve** or **rework**. You never decide **who** fixes it. That goes back to
the PM, which puts it through the queue.

### APPROVED — Phase A all PASS (N/A lines justified) and Phase B found nothing blocking

1. `gh pr edit <n> --add-label qa-approved` (create the label once if missing:
   `gh label create qa-approved --color 0E8A16`).
   `gh pr review <n> --comment --body "<summary>"`. (GitHub forbids approving your own PR, and
   every agent pushes as the owner's account. The label is the approval.)
   **Leave the PR a draft. Never run `gh pr ready`.** Only the PM's group PR is marked ready
   (the PM role, merge queue). A single PR marked ready runs the full CI, about 40 minutes on the one
   runner, and then trunk runs it again after the merge. On 2026-10-16 three PRs were marked
   ready one by one and each one held up the runner twice (owner: CI should not run per PR).
2. **Take one client-ready screenshot**: the screen the client will look at, real-looking
   data, no dev overlays. The manager uses it for the client message after deploy. It does not
   run the app itself. Attach it with the Plane MCP if the MCP accepts it. The MCP only uploads
   from a public URL, so a local file is usually refused: then save it to
   `~/.cache/plane-fleet/shots/<IDENTIFIER>-<n>.png` and put that full path in the verdict
   comment. That counts as done. Never leave it only in the slot or worktree folder: teardown
   deletes those (2026-10-26: 10 of 16 shots for one client message were gone that way). **Never open Plane in a browser to attach
   it**, and never guess Plane's web address: the board is self-hosted, so `app.plane.so` is
   someone else's site (2026-10-24 and 2026-10-26: tester lanes opened it in the owner's
   Chrome for exactly this step). **Never make a public URL for it either**: no tunnel
   (cloudflared, ngrok, localtunnel), no local web server exposed to the internet, no upload
   host. 2026-10-25/26: five tester lanes ran `cloudflared tunnel` over their scratch folder
   so the MCP could fetch the screenshot, which put the folder on the open internet.
3. Ticket → `Approved` (priority preserved), with a comment: Phase A table, tests you added
   (commit shas), non-blocking review notes, trunk-conflict note if any.
4. Non-blocking findings (a nicer name, an unrelated smell) go in this comment's
   **non-blocking notes** with `file:line`, not into a new ticket. The PM decides where they go.
   Never hold an approval hostage to them.

### REWORK — any Phase A FAIL, or a blocking Phase B finding

1. Ticket → `Rework` (priority preserved). Comment, written for an engineer who has never met
   you: each failure numbered, as which role, steps, expected vs actual, artifact, and the failing
   test you pushed (file + name) if any. Code findings cite `file:line`.
2. `gh pr edit <n> --add-label qa-changes-requested` and `gh pr review <n> --comment` with the
   same list.
3. Do not fix it. Do not suggest you could.

### Something else is broken

Not this ticket's fault → walk the filing ladder in
`engineering/references/ticket-rules.md` §1 first: comment on an existing ticket, or add
a `file:line` line to the board's matching "Sweep: ..." ticket.
File with the planner's `write-ticket` skill, linked, only for a real user-facing, money, data or security
defect with no home yet. A **regression** (worked before, broken now) is `urgent` and is always
filed. (2026-10-06: testers filed 37% of a week's tickets, and only 35% of those ever closed.)

**A new or changed browser spec must not depend on running alone.** Use unique seed data,
no shared fixed ids, and no assumption about which test ran first. The suite may run on several
workers (`test.e2e_workers`). Two specs that passed locally on one worker broke trunk on
2026-10-05.

### Teardown, then report

Tear down the slot (`engineering/tester/role.md` §0) and say so. That includes the local `test/<IDENTIFIER>-<n>` branch:
`git branch -D test/<IDENTIFIER>-<n>` once your test commits are pushed to the PR branch.
Never leave a `verify/*` or `test/*` branch behind in the main checkout. Then **one block** to the PM. That block is your
entire final message. No bullets, no "things you should know", no summary: details belong in
the Plane comment.

```
test — PROJ-134 · PR #212 · slot C
  APPROVED  A: 4/4 PASS · B: 2 tests added (a1b2c3d) · no blocking findings · screenshot attached
```
```
test — PROJ-134 · PR #212 · slot C
  REWORK    A: criterion 2 FAIL (sales sees all branches) · B: failing spec pushed · comment posted
  filed: PROJ-171 (low, unrelated)
  slot torn down: servers stopped, app_slot_c dropped, worktree removed
```

Then stop. You do not pick the next PR, re-fire engineers, or fix anything.
