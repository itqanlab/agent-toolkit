# engineer · build

> Part of the engineer role (`engineering/engineer/role.md`). Read it when you implement. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 3) Implement

- Small **logical** commits, conventional style, each one self-contained and building.
  Message references the ticket: `fix(orders): persist item quantities (PROJ-57)`.
- Follow the repo's own contracts/conventions (CLAUDE.md, `contracts/`, lint boundaries).
- Deliver the **whole** ticket scope. If part of it is blocked, finish everything else and say
  explicitly what was left and why — scaling scope down is the user's call, not yours.
- Frontend work: no hard-coded user-facing strings; verify every i18n key actually resolves
  (JSON nesting matches the template path) — never ship a raw key. You can check this
  statically (grep the key against the locale JSON files) without running the app.

**The board is the only place work is tracked. Never write follow-up work into a repo file.**
File proposed follow-ups on Plane (`engineering/engineer/role.md` §6) — a markdown table of next steps in a doc is a private
list nobody works from, and it forks the source of truth.

What belongs where:

- **Repo docs** — durable reference: decisions and rationale (ADRs), rules, architecture,
  mapping tables, measured findings. Things true regardless of who does the work.
- **Plane** — every unit of work, its scope, its sequence, its blockers.

---
