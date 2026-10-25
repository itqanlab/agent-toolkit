# PM · stop-the-line

> Part of the PM role (`core/pm/role.md`). Read it when trunk is red, or a target is down. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 1) Stop the line

**Before spawning any new engineer, before merging: is trunk green?**

```bash
gh run list --branch <trunk> --limit 3
```

Trunk red → **spawn no new engineers, merge nothing.** Testers can keep testing open PRs (their
verdict is about the PR, not trunk). Engineers already running can finish.

- **Broken by the last merge, for a code reason** → file a `Rework` ticket citing the merge,
  `urgent`, spawn a worker for it.
- **Broken by infrastructure** — stale runner cache, a flaky external — clear and rerun; when
  CI runs on a single self-hosted runner (`ci.runner` in config), a stuck job there blocks
  *everything* queued behind it, parallel workers or not. Check the runner isn't wedged before
  assuming the code is at fault.
- **Broken by the servers' daily security upgrade.** The signature: "The runner has received a
  shutdown signal" plus Postgres "terminating connection due to administrator command" in the
  same job. That's `needrestart` restarting host services after an OpenSSL/libc update. Its time
  and hosts are `ops.maintenance_window` in config (`time`, `timezone`, `hosts`). It's not the
  code: `gh run rerun <id> --failed`, and drop the scratch DB the killed job left behind. Don't
  merge a group from 10 minutes before to 30 minutes after that time, because its trunk run
  would sit in that window.
- **Broken and you cannot tell which** → revert the last merge, then file the Rework ticket.

Only when trunk is green do you resume spawning and merging.

---
