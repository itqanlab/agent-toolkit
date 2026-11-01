# PM · retro

> Part of the PM role (`core/pm/role.md`). Read it when a run starts, when the retro watcher
> exits, after each group merge, and at the end of a run. Paths written as `core/…` and
> `engineering/…` are relative to the fleet folder, three levels above this file.

## 8) Retro: the fleet checks itself while it runs

The fleet repeats its own mistakes until someone counts them. `fleet retro` counts them from
the outcome log, the session files, the lane records and the Codex meter, and prints numbered
findings, each with a cause, a fix and who owns the fix. You read the findings, not the logs.
(2026-11-01, one project: the owner asked on 2026-10-16 for a fleet self-check every 30
minutes. It lived in a private script outside the toolkit and never ran during the next run,
in which the PM spent more than all agents together.)

```bash
<fleet>/core/scripts/fleet retro --since <run start, ISO> --cwd <repo>
```

It prints the window, spend (agents and PM, the PM's share, PM context per call), one row per
ticket (rounds, spend, tool calls, time, last outcome), rework and its causes, lanes, the
Codex burn rate, then `FINDINGS`. Exit 0 healthy, 3 at least one `ALERT`. `--json` for a
script, `--hours N` for a rolling window. Thresholds and levels are in config under
`fleet.retro` (`core/references/config-schema.md`).

### When it runs

- **Every 30 minutes, through one watcher.** At run start:

  ```bash
  <fleet>/core/scripts/fleet watch retro-<project> --every 1800 \
    --until '<fleet>/core/scripts/fleet retro --since <run start> --cwd <repo> > <tmp>/retro-<project>.txt; [ $? -eq 3 ]'
  ```

  with run_in_background. It stays quiet while the run is healthy and exits on the first
  alert. When it exits, read `<tmp>/retro-<project>.txt`, act on it (below), then start the
  same watcher again. One watcher only: a second start under the name exits 75.
- **After each group merge**, once the deploy is confirmed.
- **At the end of a run**, with the whole run as the window. Its findings go into the resume
  note.

### What to do with each finding

1. **Say each finding to the owner in one line, with its number.** For example:
   `retro: PM context per call 164k, limit 150k. Fix: compact now, state is in the resume note.`
   No essay, no table paste.
2. **`who: pm`: apply the fix at once,** then log it:

   ```bash
   <fleet>/core/scripts/fleet log add --role pm --ticket <id or RUN> --executor claude \
     --model <your model> --outcome retro_fix --reason "<finding key>: <what you changed>"
   ```

   `retro_fix` rows are never refused as repeats and never scored.
3. **`who: toolkit` or `who: owner`: a proposal, with the evidence.** Name the finding, the
   numbers and the change you would make to the skill, the config or the plan. Don't edit the
   toolkit during a run.
4. **`REPEAT` means your fix did not hold.** A `pm` finding seen again in the next window goes
   to the owner as a proposal: what you changed, why it did not hold, what you would change in
   the toolkit instead.
5. **Rework findings feed the rework ledger.** A `rework_rounds` or `ticket_cause_failures`
   finding names the tickets; for each, write the step that let it through in the rework
   ledger (`core/pm/skills/spawn-tester.md`, "Cap at two reworks"), the same way as a third
   failure.

### What the findings mean

| Key | Says | Usual fix (pm unless noted) |
|---|---|---|
| `pm_ctx_per_call` | your context per call is over the limit | write the resume note and compact; read big outputs through `fleet findings` and scanners |
| `pm_share` | the PM spends too large a share of the run | the same; and stop reading logs and diffs yourself |
| `tool_calls_per_session` | one session ran past the soft cap | check the brief named the cap; split the ticket if the work is too big |
| `usd_per_ticket` | one ticket cost more than the limit | the same; a third round goes to a stronger executor, not the same lane |
| `rework_rounds`, `rework_rate` | tickets go round more than they should | rework ledger; read the causes: missed, ticket, environment |
| `ticket_cause_failures` | a tester failed a PR because the ticket was wrong | the planner fixes the ticket text before the next round |
| `duplicate_rows` | a session was logged twice | log each session once; add a field with `fleet log backfill` |
| `missing_agent_id` | a Claude spawn row has no agent id | pass `--set agent_id=<id>` on every spawn row |
| `lane_failures`, `lane_minutes` | other-CLI lanes fail or run long | move that task kind to another executor in config |
| `rewrite_share` | too much agent spend went to cache rewrites after long waits | waits of at most 4 minutes; background waits through `fleet watch` |
| `codex_pts_per_hour` | the Codex weekly meter burns too fast (owner) | lower Codex slots or move reviews to Claude |
