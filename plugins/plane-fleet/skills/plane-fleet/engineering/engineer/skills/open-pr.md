# engineer · open-pr

> Part of the engineer role (`engineering/engineer/role.md`). Read it when the change is built: local gate, browser review in your slot, PR. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 4) Local gate, browser review, PR — then stop, do not wait for CI

1. **Local gate — run it once, through the push.** The repo's pre-push hook runs exactly
   `quality.pre_push`. Don't run the gate by hand and then push, which runs it again. On
   2026-09-29 that double run cost about 8 minutes between commit and PR. While iterating, run
   only the narrow targets you touched (`nx test <project>`, `nx lint <project>`). The full gate
   runs once, when you push (step 4). First make sure the hook is installed in your worktree:
   `ls .husky/_` and, if it's missing, run `npx husky` (hooks silently skip in a fresh worktree).
   If the hook is missing and can't be installed, run the gate by hand once instead. Never
   bypass hooks (`--no-verify`); if a hook is wrong, fix the hook. Set `NX_DAEMON=false` and your
   slot's `NX_CACHE_DIRECTORY` first.

2. **Run it in your slot and look at it.** Bring up your slot with the repo's recipe
   (`fleet.slot_recipe` in config): your ports, your slot DB, migrated and seeded, server and
   client from your worktree. Check the slot is free first; if a port or the DB is taken, stop
   and report — never fall back to the shared ports.

   Then review your own change in a browser (your own Playwright/Chromium, never the owner's
   Chrome):
   - walk every acceptance criterion **as the role it is about**, not owner
   - **every role, language and entry point the DoD names, not the first one that works.** If
     the DoD names two roles, walk both. If it names two languages, walk both. If
     the screen opens from the list and from a detail page, open it from both. A combination
     you skip goes in your handoff as `not walked: <what> (<why>)`. It never goes silently.
   - **a ticket that says "everywhere", "all", or "every X" needs a scripted sweep**, not a look
     at the sites you remember. Write the grep/AST search that finds every instance, run it
     after your change, and paste the command and its (empty or allowlisted) output into the
     handoff.
   - the empty state, the error path, the other role, the default locale (`i18n.default`;
     right-to-left if it is one)
   - no raw i18n keys on screen, no console errors, no 4xx/5xx you did not expect
   - fix what you find, re-run the gate, look again

   Why this is spelled out: in the 2026-09-29→10-01 run, 7 of 7 rework fails were thoroughness
   gaps (a missing retry button, a focus bug, a confirm that survived Back, a missing print total),
   one role, one language or one path. A "one digit style everywhere" ticket failed twice because
   each pass fixed only the sites the engineer looked at.

   Take a screenshot per criterion for your handoff. This is **your** check. It does not replace
   the tester's, and the tester will not read it before doing their own. Write down plainly
   anything you could not reach.

3. **Tear down the slot** — stop both servers, drop your slot DB, free the ports. A slot you
   leave running blocks the next session assigned to it.

   **3b. Independent code review, before you push.** Commit, then run a fresh review of your
   whole diff against the trunk:
   ```bash
   codex review --base origin/<trunk> > /tmp/<TICKET>-review.md 2>&1
   ```
   It runs in a new process with none of your reasoning, so it is not you marking your own
   work. Start it in the background as soon as you commit, next to your narrow tests, so it
   costs little wall time.

   **When your brief carries a focused review prompt, run that one too**, the same way:
   `codex review "<the prompt from your brief>" > /tmp/<TICKET>-review-focused.md 2>&1`. It
   names the ticket's invariants and the findings already deferred elsewhere, and it is the
   review the PM runs after you. A generic pass calls a PR clean far more often than a focused
   one does.
   - **Every P1 and every P2: fix it, commit, and run both reviews again.** Repeat until one
     full pass of each reports no P1 and no P2. Report how many passes it took.
   - **Fix the class, not the line.** For every finding, find its siblings before you fix it:
     every writer of that field, every path that books that money, every caller of that
     function (grep the whole repo, not the files you touched). Fix all of them, and put the
     list of sites you checked in the handoff.
   - **A P2 you believe does not apply: stop and ask the PM before you push.** Never leave one
     open with a note. On money, privacy, auth and audit tickets a P2 blocks.
   - P3 and style notes: your call.
   - A finding that is real but outside the ticket goes through `engineering/engineer/skills/follow-ups.md` §5 (file it, don't work it).
   - The review being unavailable (CLI missing, auth error) is a blocker to report (`engineering/engineer/role.md` §7), not a
     step to skip.

   Why: on 2026-10-15/16 two Sentry tickets each passed engineer and tester, then the group
   review found 5 privacy defects, then 2 more, then a race. That was three full
   engineer + tester rounds, about 50 minutes each, for defects a 5 to 10 minute review on the
   engineer's own diff would have caught in the first run.

   Why it loops on P2s and wants the whole class (2026-10-26 to 28, one project, 34 tickets):
   only 12 shipped in one round and 14 took three or more; rework was at least 15 of 25
   engineer hours. Each review pass found one or two new issues next to the last fix. One
   audit event was missing on one path, then on a second, then written twice on a third
   (9 rounds). Two P2s left open "on purpose" came back as blockers.

4. Push (the hook runs the full gate here; a failure means fix and push again) and open the PR:
   ```bash
   git push -u origin <branch>
   gh pr create --draft --base <trunk> --title "<type>(<scope>): <what> (<TICKET>)" \
     --body "<what / why / how you checked it: gate + browser walk>"
   ```
   **Always open it as a DRAFT.** On repos whose CI skips heavy jobs for drafts, a draft runs only the cheap checks, and the full CI runs once, on the PM's
   group PR. Nobody marks a single ticket's PR ready (owner, 2026-10-16). Your local pre-push gate already ran the full suite. A rework
   engineer pushes to the same draft PR and leaves it as a draft. If the PR is already ready (a
   rework after approval), leave its state alone.

5. **Ticket → `In Review`** (priority preserved), post the handoff comment (`engineering/engineer/role.md` §6), hand back.
   Do **not** poll `gh pr checks`. CI runs on one self-hosted runner and queues behind every
   other push; waiting for it inside your session re-serializes the work. The tester starts on
   your PR now, and the manager checks CI in the merge queue.

6. **Remove your worktree and your local branch** once the branch is pushed. The PR lives on
   the remote, and a rework engineer starts from `origin/<branch>`:
   ```bash
   cd <repo-root> && git worktree remove .claude/worktrees/<slug> --force
   git branch -D <branch>     # safe: it's on origin; check `git ls-remote --heads origin <branch>` first
   ```
   Never stash to set work aside. Commit it (WIP is fine) and push. A stash is invisible to
   everyone else and outlives its reason. (2026-10-02: 96 local branches and 3 stashes up to 4
   months old had piled up in the main checkout, all of it already landed or abandoned.)

---
