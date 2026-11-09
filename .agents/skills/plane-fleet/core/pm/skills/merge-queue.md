# PM · merge-queue

> Part of the PM role (`core/pm/role.md`). Read it when approved PRs wait: you alone merge, in groups. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 5) Merge queue — you alone merge

A PR is eligible when **all** hold: ticket `Approved`, label `qa-approved` present, CI green on
its latest commit, trunk green (`core/pm/skills/stop-the-line.md` §1), and, for a schema PR, no other schema PR in
the same train.

**Schema PRs, one per train.** Schema tickets build in parallel (`core/pm/skills/pick.md` §2), so
several schema PRs can be approved at once. Land the oldest first, in a train of its own. Before
the next one merges, its branch is rebased onto the new trunk and its migration folder is
re-stamped to sort after trunk's latest; then it runs the repo's deploy-style migrate on a fresh
slot DB and the schema validator, and its CI goes green again. A clean rebase with only the
re-stamp is a mechanical step and yours. A conflict inside the schema file is an engineer lane.

1. **Order:** dependencies first, then oldest-approved, then by area.
2. **Land one at a time**, each on the trunk the previous one produced:
   ```bash
   gh pr merge <n> --merge --delete-branch
   git checkout <trunk> && git fetch origin && git reset --hard origin/<trunk>
   ```
   **A branch another open PR is based on is never deleted at merge.** Check first:
   `gh pr list --state open --base <head branch of n>`. If anything is listed, merge `<n>`
   without `--delete-branch`, move each listed PR to the trunk with
   `gh pr edit <m> --base <trunk>`, and delete the branch only after that. GitHub closes a PR
   whose base branch is deleted, and a closed PR cannot be retargeted, only re-filed as a new
   PR (2026-10-17: a stacked PR closed this way and had to be re-filed).
   For each next PR: `gh pr update-branch <n>`, then **wait for its CI to go green again** before
   merging. This is the one place anyone waits for CI, and it is you.
3. **Conflicts:** a mechanical rebase is yours. Anything that changes behaviour is not — send the
   ticket to `Rework` with a comment naming the conflicting PR, and remove `qa-approved`.
   **Shared-registry conflicts are mechanical, and they are yours** (i18n JSON, error codes,
   audit actions, DTOs, permission matrix + spec + contract, module providers, route table).
   Merge the trunk into the PR branch in a scratch worktree, keep both sides' additions, then
   **dedupe**: git auto-merges two PRs that each added the same entry into a duplicate without
   flagging a conflict (2026-10-08: `hr:self` landed twice in permission-matrix.ts, the
   contract table and both settings.json files). `grep -c` each key you kept. Then run
   typecheck + the affected tests with `--skipNxCache`, and push through the hook. Expect it:
   in an area where every ticket adds a permission, each merge conflicts the next PR.
4. **Tester commits land with the PR.** If the tester pushed tests after approving, CI has to be
   green with them included.
5. **Write each ticket → `Merged` right after its own merge**, comment naming the merge commit.
6. Merge up to `fleet.merge_train_size`, then let the deploy settle (`core/pm/skills/deploy-and-done.md` §6) before the next train.

**Draft-only fleets: one group PR, and it is the full check** (owner, 2026-10-13 and
2026-10-15). When engineers open drafts and testers leave them draft, the PM builds
`release/group-<date>-<n>` from about 10 approved branches, runs the pre-push gate and a Codex
review (`codex review "<instructions naming the base>" > <tmp>/group-<n>-review.md 2>&1`;
`--base` cannot be combined with a prompt), reads it only through `fleet findings <that file>`,
and opens ONE PR into the trunk. Per-PR CI skips most jobs on drafts, so the group PR carries
all the risk: keep a group small (about 5) when it includes a shared UI change or a dependency
change. That PR is where the whole server and browser suites
run, so testers no longer run them per ticket (the tester role). Ticket PRs stay drafts the whole
way: never mark one ready and never put the e2e label on one. A draft ticket PR still shows as
merged once its commits reach the trunk through the group. To make sure the suites really run:
- open the group PR **as a draft**, add the e2e label, and only then `gh pr ready`. A label
  passed to `gh pr create --label` is applied after the opened event, so CI never sees it
  (2026-10-14: the full browser suite was skipped on group 1, and 3 reds surfaced on develop).
- check the run's scope step printed the label as present (`HAS_LABEL: true` on this repo)
  and that the browser job reads SUCCESS, not SKIPPED, before merging.
- **Check the group PR is mergeable before you wait on it.** A group branch cut before an
  earlier group merged can conflict with the trunk. GitHub then starts no pull_request checks
  at all, and a watcher waiting for success only times out. So run
  `gh pr view <n> --json mergeable,mergeStateStatus` first. Not mergeable: merge the trunk into
  the group branch (a merge commit; keep both sides of changelog-style rows), rerun the full
  local gate, and push. Then look for clashes a text merge cannot see, such as both groups
  adding the same method to one class. A watcher treats "no checks after N minutes" as a fault
  to report, never as pending.
- **When the group PR doesn't run the full suites** (some projects save them for the release
  to production), the builder still runs every test file that covers code the group changed,
  not only the specs the tickets name. Find them by what imports the changed modules (the
  project's affected-test command, or a grep for the module names in the test folders). A
  group that breaks a test nobody ran surfaces a day later on the release.
- **No release waits on one ticket by default.** When the owner wants to release and one
  ticket is still in rework, say plainly what holding costs: whether users can see the change
  at all, how many rounds it has had, and a rough wait. Let the owner choose. A ticket with no
  user-visible change doesn't hold a release unless the owner says so.
  (2026-10-30, one project: a group broke a server test no group run covered, and a release
  waited about 3 hours on a server-only ticket that users couldn't see yet.)
- **When `ci.group_is_the_gate` is on, the group PR's CI is the only full run.** Do not run
  `quality.pre_push_full` on the group branch and do not use the gate stamp below. Push, let CI
  decide, and fix on the group branch until it is green. Merge only when it is green on the
  latest head and the trunk has not moved since that run: `gh pr view <n> --json mergeStateStatus`
  must not read `BEHIND`. If it does, update the branch and let CI run again. Untested code
  reaching the trunk is the one thing this rule must never allow. Platforms without branch
  protection cannot enforce it, so you do. A project may skip trunk CI after the merge only when
  the trunk commit holds exactly the code the PR passed on, and must run it in full otherwise.
  (2026-11-09, one project: the same code ran on the PR and again on the trunk, on two runners
  with separate caches, and reused almost nothing.)
- **Land a run in a few bigger groups, not one per approval.** Each group costs a full CI cycle
  and a deploy, in series. Build a group when `fleet.merge_train_size` tickets are approved, or
  when nothing still building could join it within about the length of one CI cycle.
  (2026-11-08, one project: 6 groups of 1 to 6 tickets took about 7 hours of merge and deploy.)
- **A chain of dependent tickets lands as one group, in order.** See the planner's stacking rule.
  A fix to an earlier ticket in the stack is merged forward into the later branches before the
  group is built.
- **Merge a group PR on the local gate stamp, not on a CI rerun of it.** (Not with
  `ci.group_is_the_gate`.) When
  `ci.covered_by_local_gate` names CI jobs your pre-push gate already runs (lint, typecheck,
  unit tests, build on what is affected), waiting for them repeats the same work on the same
  commit. So:
  1. Run the gate on the group branch with its result in a log:
     `{ <quality.pre_push>; echo "pre-push exit $? at $(git rev-parse HEAD)"; } > <tmp>/group-<n>-gate.log 2>&1`
     (or capture the `git push` whose hook ran it, ending with the same line). Push that commit.
     Take the gate lock first (standing brief); only one full gate runs on the machine at a time.
     **A plain git pre-push hook does not print that line**, so a push log alone never matches.
     Until `gate-stamp` reads the hook's exit status (CHANGELOG 2.10.0, Proposed), prove the
     gate passed another way: after `git push` without `--no-verify`, the remote branch head
     (`git ls-remote origin <branch>`) equals the local HEAD. The push only lands when the hook
     passes. **Nobody writes that log line by hand.** A stamp built on a hand-written line is
     rejected, and the gate runs again. (2026-11-04, one project: a session wrote the line itself,
     and the PM rejected the stamp.)
  2. `fleet gate-stamp post --cwd <group worktree> --sha <head> --log <that log>`. It refuses
     unless HEAD is that commit, the tracked tree is clean and the log shows the gate passed
     on it. It posts the `local-gate` commit status with the machine and the duration.
  3. `fleet gate-stamp check --pr <n>`. Exit 0 means the stamp is on the PR head and every
     check that is not covered passed or skipped. Merge then, even while a covered job still
     runs. Cancel a covered job only when no other job of that run still waits on it: a job
     that `needs` it gets skipped, and the check counts that skip as not passed.
  - Never for the release PR to the production branch: that one waits for its full CI.
  - Never when the head moved after the stamp (a new commit, a rebase, an update-branch). The
    stamp belongs to one SHA; gate and stamp again.
  - Trunk CI after the merge still runs everything and stays the deploy gate. A red trunk is
    handled as always (`core/pm/skills/stop-the-line.md` §1).
  (2026-11-01, one project: each group PR waited about 15 minutes for a CI job that re-ran the
  lint, typecheck, test and build the PM's gate had just passed on the same commit, and trunk CI
  ran them a third time after the merge.)
- a red group PR: match the failing spec to its PR (`gh pr view --json files`), drop that
  branch from the group, rebuild, and send its ticket to Rework.
- a red group PR you fix in place instead: split the failures by effort. The easy ones (a
  snapshot, a test's own race) are pushed first, in one lane. Each hard investigation gets its
  own lane, so it never holds up the easy fixes. Check on every group-fix lane at 30 minutes.
  While one runs, allow at most one other heavy session on the machine. (2026-10-27: a group
  of 8 took about 4.5 hours, and the work itself took about 1.5. A 20-minute fix waited
  behind a 3-hour investigation in the same lane, on a machine at a load of 36 to 61, and the
  PM first asked for a status 2.5 hours in.)

**Merge in groups of about 5 when the browser suite only runs on trunk.** Many repos keep PR
CI short (affected lint, typecheck, unit and API tests) and run the browser e2e suite only on
the trunk push after a merge, unless the PR carries the full-e2e label (`ci.e2e_label` in
config). Then "CI green" on a PR doesn't include the browser suite, and the trunk run after a
group is where it gets checked:
- Pick up to ~5 approved PRs with green PR CI and no shared files, and merge them back to back.
  One develop run covers them all.
- Keep a group to ~5 PRs. If trunk goes red in the browser suite, the failing spec names the screen;
  match it to the PR in the group that touched that screen (`gh pr view --json files`). Revert
  only that PR, send its ticket to `Rework`, and let the rest of the group stand. Unclear →
  revert the whole group and re-merge it in halves.
- A PR that changed shared UI goes in a group of its own, or its group PR carries the e2e label.
- **Two PRs that change the same shared component never go in one group.** Shared means
  the paths in `fleet.shared_ui_paths` (for example the UI library, the form contract, the table
  and field components). Hold the second PR until the first group's trunk run is green.
  2026-10-05: three PRs sharing a form component each passed testing on their own, then broke
  trunk together and all three were reverted.
- **A group that adds or changes a browser e2e spec needs a green e2e-labelled run on its group
  PR before it merges.** If the suite runs on several workers, a local pass on one worker doesn't count. The
  label must be on the PR **before** the push that triggers the run: adding it afterwards
  doesn't re-run CI, and the e2e job shows `SKIPPED`. Label first, then push or
  `gh pr update-branch`. Check that the e2e job reads SUCCESS, not SKIPPED, before merging.
- **When trunk goes red, check the failing spec against the group with `gh pr view --json
  files` before reverting.** Revert the PR that owns that spec or screen. 2026-10-05: the PM
  reverted a PR on a guess; the failing spec belonged to another PR in the group.

Measured basis: with the browser suite on every PR, 10 approved tickets needed about 3 hours of
single-runner time to reach dev. With it on develop only, it's about 1 hour.

**Batch the train. Don't merge the moment one PR is ready.** Each merge costs a full trunk CI run
plus a deploy, about 15 minutes on the single runner, and until it's `Done` it blocks the next
train. If another PR is in `Testing` and its tester started more than ~10 minutes ago, hold the
approved one and merge both together: one trunk CI, one deploy, one confirmation. Measured
2026-09-29: merging two approved PRs one at a time cost two trunk runs and two deploy waits, about
35 minutes. Holding the first for 11 minutes would have saved most of that. Don't hold longer than
~20 minutes, and never hold for a PR still with an engineer.

**Skip `update-branch` when the PRs don't share files.** For the second and later PRs in a train,
compare its changed files with those of every PR merged ahead of it (`gh pr view <n> --json
files`). If there's no overlap and GitHub reports `mergeable: MERGEABLE`, merge it directly
without updating the branch and re-running PR CI. Trunk CI after the train tests the combined
code, and a red trunk still stops the line (`core/pm/skills/stop-the-line.md` §1). Update and re-run only when files overlap, or
when GitHub says the branch is behind in a way that blocks the merge. Measured 2026-09-29: an
`update-branch` on disjoint files cost a 22-minute PR CI rerun.

**Merge the whole train back to back, so trunk runs once.** Merging PRs a few minutes apart
starts a separate trunk run for each one. Land them together, then check for superseded trunk runs:

```bash
gh run list --branch <trunk> --status queued --json databaseId,headSha,createdAt
```

A queued run for an older merge commit is redundant: the newest run tests everything it would
test, and it also carries the deploy. Cancel it (`gh run cancel <id>`) and track only the newest
run for `Done`. Never cancel a run that has **started**, because it may be mid-deploy. Say which
run you cancelled and which one you're tracking. (Done by hand on 2026-09-30: a queued run was cancelled because the next merge's run
contained it. That freed about 20 runner minutes.)

**Let trunk and urgent fixes jump the runner queue.** The single runner serves jobs first come,
first served, and a job only joins the queue once the job before it in its run finishes. So a
trunk run's e2e jobs, or an urgent fix's CI, can sit behind a long tail of PR runs. To move one
to the front:
- cancel queued PR CI runs that have no job **running** right now (runs whose first job already
  passed count too), and save their ids
- when the priority run is done, `gh run rerun <id> --failed` for each saved one. That re-runs
  only the cancelled jobs and keeps the ones that passed.
Never cancel a job that is running. (2026-09-30: used twice. A trunk run and an urgent fix each waited behind 6+ PR runs.)

### The release PR to production

The release PR from the trunk to the production branch waits for its full CI, the whole e2e
suite included. Two things make that run fail or never start:

- **A change drawn on every page fails every visual baseline.** When a release changes the
  navigation, the header or anything else on every screen, regenerate the baselines before the
  release e2e run: on the CI runner, never on a developer machine (fonts differ), from a branch.
  Look at a couple of old and new images by eye, then merge that branch. A diff of a few pixels
  inside text is anti-aliasing noise, not a change.
- **`[skip ci]` on the newest trunk commit skips the release PR's runs too**, when the PR head is
  that commit. Never merge a `[skip ci]` commit last before you open or update a release PR. If
  it happened, push or merge a normal commit, or close and reopen the PR.

---
