# engineer · build

> Part of the engineer role (`engineering/engineer/role.md`). Read it when you implement. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 3) Implement

### 3a. Path map before code (trial: `fleet.trials.path_map`)

Only when the trial is on in the project config, and the ticket changes a money, stock, state or
permission rule. Before you write code, find every place that rule runs: each entry point (create,
edit, store order, online order, exchange, retry, import), each writer of the fields it sets, each
screen that shows a preview of it. Search the whole repo, not the files you expect to touch.
Post it on the ticket as one comment that starts with `PATH MAP:`, one row per path:

| Path | Where (`file:line`) | What the ticket needs there | How a tester reaches it |
|---|---|---|---|

Rows the ticket does not cover are listed too, marked `out of scope: <ticket that owns it>`.
Then build every in-scope row, and keep the map current if you find a new path. The tester
checks every row in round 1. Why: measured 2026-11-16 on one project, most failed test rounds
were the same rule breaking on a path nobody had listed yet, found one path per round, and three
releases of "fix the class" rules did not move the rework rate (39-67% in every run).

### 3b. Build to the case list (trial: `fleet.trials.case_list`)

Only when the trial is on in the project config and the ticket has a `CASE LIST:` comment
(`engineering/references/case-list.md`). The list is the definition of done.
- The handoff gives a pass or fail per case number, each from a real run (a command or a
  browser step), never from reading the code.
- A rule over a grid ships with ONE parametrised test over the whole grid (every width,
  language, mode, position and engine in `fleet.client_engines`) before the first push.
- Self-review passes (`engineering/engineer/skills/open-pr.md` §4.3b) start once the cases are
  green.
- Fix the cause, not the case. A fault in one cell of a grid comes back with why that cell
  differed from the others, and the fix is there.

- Small **logical** commits, conventional style, each one self-contained and building.
  Message references the ticket: `fix(orders): persist item quantities (PROJ-57)`.
- Follow the repo's own contracts/conventions (CLAUDE.md, `contracts/`, lint boundaries).
- Deliver the **whole** ticket scope. If part of it is blocked, finish everything else and say
  explicitly what was left and why — scaling scope down is the user's call, not yours.
- Frontend work: no hard-coded user-facing strings; verify every i18n key actually resolves
  (JSON nesting matches the template path) — never ship a raw key. You can check this
  statically (grep the key against the locale JSON files) without running the app.
- **A change to what a screen shows makes old specs stale.** When the ticket removes, renames
  or moves a text or a figure on screen, grep every end-to-end spec for it and update those
  specs in the same PR. (2026-11-04, one project: a release e2e run failed on a spec that still
  expected a figure the ticket had replaced on purpose.)

**The board is the only place work is tracked. Never write follow-up work into a repo file.**
File proposed follow-ups on Plane (`engineering/engineer/role.md` §6) — a markdown table of next steps in a doc is a private
list nobody works from, and it forks the source of truth.

What belongs where:

- **Repo docs** — durable reference: decisions and rationale (ADRs), rules, architecture,
  mapping tables, measured findings. Things true regardless of who does the work.
- **Plane** — every unit of work, its scope, its sequence, its blockers.

---
