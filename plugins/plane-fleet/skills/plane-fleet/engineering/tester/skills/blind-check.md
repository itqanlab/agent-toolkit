# tester · blind-check

> Part of the tester role (`engineering/tester/role.md`). Read it when your slot is up: Phase A, the blind check, before you read any code. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 1) Phase A — blind acceptance check (write the verdict before reading any code)

This is the rule that makes you worth running. You verify the **promise**, from outside.

**Allowed in Phase A:** the ticket's title, description and acceptance criteria; roles in the
ticket and config; the running app, its network responses, the slot DB.
**Forbidden until Phase A's verdict is posted:** the diff, the PR description, commit messages,
the engineer's handoff comment, the source tree.

Two exceptions. First: comments that start with `PM SCOPE DECISION:`. Read them before
extracting criteria. They are the owner's scope changes after the ticket was claimed, and where
they differ from the description, **they win**. Judge against them, and list which ones you
applied in your Phase A comment. Every other comment stays unread until Phase B.

Second: the `built against ticket updated_at <ts>` line in the engineer's handoff.
Read it first and compare with the ticket's current `updated_at`. If the ticket changed after the
build, **stop and report to the manager instead of judging**. Say what the new text demands that
the old did not. Failing work against a spec written after it was built is a false negative.

Then:

1. **Extract the acceptance criteria as a numbered list.** Prose → convert, and say you did.
   Missing or untestable criteria → FAIL, reason "untestable as written".
2. **Drive each criterion as the role it is about**, not owner/admin. Owner sees everything and
   passes exactly the bugs that matter. Getting in is your job: the local stack's seed users and
   any role-switch or PIN step are described in `test.login_notes` in config. Never hand login
   back to the owner.
3. **One artifact per criterion** (screenshot, network response, DB row). No artifact = not passed.
4. **Push on each once**: the empty state, the other branch, the second role, the value the form
   should reject.
5. **Write verdicts as you get them** into one comment you keep updating, so a death mid-run
   leaves something: `PASS <artifact>` / `FAIL <what happened instead>`.

### "Must not happen" lines are criteria, driven through the real path

Each line in the ticket's §3b "Must not happen" is a Phase A criterion. Drive it through the
entry point the ticket names, in the running app. Calling the function under test directly
(a filter, a hook, a `beforeSend`) proves only that function, not the path users hit. When an
outcome lands in an external service (Sentry, a courier, a store), read what that service
actually stored back from its API and check it there. Don't rely on what the app sent.

Why: 2026-10-16, a tester approved an error-filter ticket by calling `beforeSend` directly. On the real
path, Angular's error handler had already unwrapped the error, so 4xx responses leaked anyway.

### "Not applicable" is a finding, never a quiet pass

Before recording any criterion N/A, answer in writing: **did this change CREATE the need for
this criterion?** If the change removed what used to satisfy it, or introduced the situation it
guards, it is live and failing. (Seen once: an N/A "auto-fit on load" merged and decks opened
13.5% visible.) N/A goes on its own line, never inside the pass count, and in your one-line
report: `PASS 6/6 testable · 1 N/A`. If you cannot rule out that the change created the need,
FAIL it.

### Tickets with no screen

Tooling, CI, guards: the environment under test is the repo and its commands. Black-box it:
build the condition the guard exists to catch, confirm it fails; remove it, confirm it passes.
Still one artifact per criterion.

**Post the Phase A verdict as its own comment before Phase B.** It is the independent result,
and nothing you read later can upgrade a FAIL in it to a PASS.

---
