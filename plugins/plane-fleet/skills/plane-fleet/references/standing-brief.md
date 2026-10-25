# Standing brief — every /team-engineer and /team-tester session

The PM's spawn brief tells you to read this file first. Everything here is part of your brief,
exactly as if it had been pasted in. Ticket-specific context (ticket, slot, PR, owned files,
decisions) comes in the brief itself.

## STANDING BOUNDARIES (apply to every ticket, no exceptions)

- Never change a budget, threshold, limit, timeout, lint rule, or CI config to make your work
  pass. If your change cannot land without one, STOP and report with numbers. Raising a gate is
  the manager's decision, never yours — a gate you widen protects nobody afterwards.
- Never edit a file owned by another open PR (list given in your brief). If your fix genuinely
  needs one, STOP and say so rather than editing it or working around it. Exception: the
  SHARED REGISTRY rule below, when your brief names those files.
- Never disable, skip, or weaken a failing test. Report it.
- Prefer your own Playwright/Chromium over the shared browser; create your own tabs, close only
  what you opened, never resize or close a window you did not create.
- Run your app/API/DB ONLY on your assigned slot (ports, DB, Nx cache given in your brief).
  Never use the shared row. Slot occupied → stop and report. Tear it all down before you report.
  No slot in your brief → skip the app/browser steps and say so.
- Before any nx command: NX_DAEMON=false and your slot's NX_CACHE_DIRECTORY.
- After starting your API, confirm it listens on YOUR slot's api port (`lsof -iTCP:<api>
  -sTCP:LISTEN`). If it bound the shared row's port instead, the port env wasn't exported: kill
  it at once. Stop processes only by your own ports, never `pkill -f`/`killall`.
- `nx affected` can serve results from another session's cache — re-run with `--skipNxCache`
  before trusting a green.
- Never bypass a hook: no `--no-verify`, no `HUSKY=0`, no `-n`. A hook failure you believe is not
  yours is a report with the failing output, never a skip. In a fresh worktree, run `npx husky`
  first (hooks silently don't run until you do).
- Temp and cache dirs are yours alone: use your slot's, or `/tmp/<TICKET>-<role>` if you have no
  slot. Never use, clean or delete a directory another session was given.
- **Leave nothing running.** Memory is the fleet's tightest resource: one headless Chromium
  costs about 500 MB, one API server 200-300 MB, and seven slots pushed a 32 GB Mac into
  17 GB of swap (2026-10-14). So:
  - Launch ONE browser per session and reuse it (new contexts or pages, not new browsers).
    Close every context when you are done with it, and the browser in a `finally`, so a
    failed script cannot leak it.
  - Launch Chromium with `--renderer-process-limit=2 --disable-gpu --disable-dev-shm-usage`
    and with trace, video and HAR off unless a check needs them. A screenshot only when you
    will look at it; delete it once you have.
  - Point the browser's user-data-dir (or `cwd`) inside your slot's scratch dir, so a leftover
    can be traced to its slot.
  - Never start an Nx daemon (`NX_DAEMON=false` in every shell you run nx from).
  - Teardown is not done until these all print nothing: `lsof -iTCP:<api> -sTCP:LISTEN`,
    `lsof -iTCP:<client> -sTCP:LISTEN`, `pgrep -f "<your slot scratch dir>"`, and
    `pgrep -f nx/src/daemon` filtered to your worktree path. Kill what is yours; report
    anything else you find instead of killing it.
- Run `git config core.bare` before and after any test run. It must print `false`. If it prints
  `true`, run `git config core.bare false` and say so in your report.
- Report what you could NOT demonstrate as plainly as what you could.

## SHARED REGISTRY FILES (only when your brief lists them)

Some files are append-only registries every feature touches: i18n JSON, error-code and
audit-action lists, DTO barrels, permission matrices and their contract docs, module provider
lists, route tables. When your brief names them as shared registries, you MAY make **additive**
edits there even though another open PR also touches them:

- add new entries only; never reorder, rewrite or delete existing ones
- never add an entry the other side already added (search develop and the other PR first)
- before you push, `git fetch` and rebase/merge onto the trunk; resolve conflicts in those
  files by keeping both sides' additions, then dedupe
- any conflict outside those files → stop and report

## BEFORE YOU REPORT

- Anything you found that needs work outside this ticket: walk the filing ladder in
  `references/ticket-rules.md` §1 BEFORE filing.
  1. Small and in a file you already touch? Engineer: fix it in this PR. Tester: put it in your
     verdict notes.
  2. Already covered? Comment on that ticket.
  3. A sweep pattern (wrong-language names, route vs API role, raw keys)? Add a file:line line
     to the sweep ticket.
  4. A post-release check? Add it to the Release checklist ticket.
  5. Only a real user-facing, money, data, security or blocking problem gets a new ticket
     (/team-ticket-writer). Name its id in your report.
  Nobody will wake you up later to do it.
- At most 2 new tickets per session. More than that → file ONE ticket listing them all, and the
  PM splits it if needed. A post-merge step for this ticket is exempt and always gets its own
  ticket. Before filing, search the board (list + grep, not search) for an existing ticket that
  already covers it, and comment there instead.
- A PR that adds or changes a browser/e2e spec: add the repo's full-e2e label (e.g. `run-e2e`)
  BEFORE your last push. A label added after the push does not re-run CI.
- Your FINAL message is ONLY the report line/block your skill specifies. No summary, no bullets,
  no "things you should know". Everything else goes in the Plane comment.
