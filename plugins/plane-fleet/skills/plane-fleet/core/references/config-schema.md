# Project config — `.plane/config.json` plus a private per-user override

Two files, merged. Every value the fleet needs about a project lives in them. Nothing about a
project is hard-coded in the skills.

1. **`.plane/config.json`** at the repo root. Committed, so every session sees the same wiring.
   Put here what is safe to share with anyone who can read the repo.
2. **`{state_home}/projects/<repo-name>.json`**, outside the repo (`{state_home}` is
   `PLANE_FLEET_HOME`, default `~/.config/plane-fleet`). Same shape, deep-merged over the repo
   file, and it wins. Put here what is private to you: the client's name and contact ids, server
   names, your timezone, a maintenance window.

Read the merged result with `core/scripts/fleet config [--get a.b.c]`. Objects merge key
by key; lists and plain values replace.

```jsonc
{
  "plane": {
    "workspace_slug": "my-workspace",
    "project_id": "00000000-0000-0000-0000-000000000000",
    "identifier": "PROJ",                // ticket prefix, e.g. PROJ-57
    "mcp_issues": "https://github.com/<org>/<plane-mcp-fork>/issues"   // where a missing MCP capability gets filed
  },

  "owner": {
    "timezone": "Europe/Berlin"          // durations and times in reports use it
  },

  "git": {
    "trunk": "develop",                  // integration branch; PRs target this
    "remote": "origin",
    "merge_strategy": "merge",           // merge | squash | rebase, passed to `gh pr merge`
    "branch_pattern": "<type>/<IDENTIFIER>-<n>-<slug>"
  },

  "quality": {
    "pre_push": "npm run quality:pre-push",   // MUST pass locally before the PR
    "commit_style": "conventional"
  },

  "ci": {
    "provider": "github-actions",
    "required_green": true,
    "required_jobs": ["lint", "unit", "api-e2e", "browser-e2e", "deploy-dev"],  // a watcher waits for these by name
    "e2e_label": "run-e2e",              // label that makes PR CI run the full browser suite
    "runner": "a single self-hosted runner",   // say so when one runner serves every job
    "runner_cache": "/path/to/runner/build-cache"   // persistent build cache to move aside when it serves stale output
  },

  "test": {
    "e2e_dir": "apps/web-e2e",           // browser e2e project
    "e2e_spec_dir": "apps/web-e2e/src",  // where new specs go
    "e2e_run": "npx playwright test <spec>",   // run one spec against your slot's ports
    "e2e_workers": 2,                    // workers the suite runs with in CI
    "login_notes": "Seeded users per role are listed in the README; passwords in .env.local. No PIN."
  },

  "i18n": {
    "default": "en",                     // walk this one first; say if it is right-to-left
    "locales": ["en", "de"]
  },

  "ops": {
    "maintenance_window": { "time": "03:00", "timezone": "UTC", "hosts": ["ci-runner-1", "app-server-1"] }
    // host security upgrades restart the runner and its database; don't merge a group into it
  },

  "deploy": {
    "platform": "github-actions",        // any PaaS or CI; the PM reads the note below
    "note": "dev auto-deploys on every push to develop; scripts/deploy.sh is break-glass only",
    "environments": [
      { "name": "dev",  "branch": "develop", "url": "https://dev.example.com", "health": "https://api.dev.example.com/v1/health" },
      { "name": "prod", "branch": "main",    "url": "https://app.example.com", "health": "https://api.example.com/v1/health" }
    ]
  },

  "client": {                            // usually lives in the per-user override, not the repo
    "name": "Sam (the client)",
    "channel": "none",                   // none | mcp-message | a skill name; see engineering/references/notify.md
    "mcp_server": "my-messaging-server", // channel mcp-message: the MCP server that sends
    "account_id": "…",
    "conversation_id": "…",
    "language": "en",
    "register": "friendly, plain language, no jargon"
  },

  "roles": ["owner", "admin", "manager", "staff"],
  // roles that must be exercised when verifying a permission/scope ticket

  "fleet": {                             // read by the PM role, the engineer role, the tester role
    "merge_train_size": 3,
    "parallel_workers": 2,               // engineers at once
    "parallel_schema": 2,                // schema tickets building at once, on disjoint models (pick.md §2)
    "slot_policy": "one pool",           // testers take ANY free slot; no fixed tester cap
    "slots": {                           // one per running engineer/tester; never assign "shared"
      "shared": { "api": 3000, "client": 4200, "db": "app_dev" },
      "A": { "api": 3010, "client": 4210, "db": "app_slot_a", "nx_cache": "$HOME/.cache/plane-fleet/slot-a/nx-cache" },
      "B": { "api": 3020, "client": 4220, "db": "app_slot_b", "nx_cache": "$HOME/.cache/plane-fleet/slot-b/nx-cache" }
      // add redis / bucket keys per slot if the app uses them
    },
    "slot_scratch_prefix": "/tmp/proj-slot-",  // OPTIONAL. Scratch dir is <prefix><slot>; default /tmp/<plane.identifier lowercased>-slot-
    "cost": {                            // OPTIONAL, for `fleet cost`
      "claude_project_dirs": ["-old-path-to-repo"]   // extra Claude Code project folders (names or globs), for a repo that moved
    },
    "slot_recipe": {                     // exact per-repo commands, <placeholders> from the slot
      "prereq": [], "free_check": [], "env": [], "up": [], "down": []
    },
    "schema_paths": ["prisma/schema.prisma", "migrations/"],   // a change here makes a ticket a schema ticket
    "schema_notes": "generated columns must be hand-edited out of new migrations; see CONTRIBUTING.md",
    "shared_ui_paths": ["libs/ui/**", "src/app/shared/forms/**"],  // two PRs touching these never merge in one group
    "executors": {                       // OPTIONAL. Deep-merged over core/references/executors.json
      "candidates": {                    // see core/references/executors.md for the layers
        "engineer": { "*": [ { "executor": "claude", "model": "sonnet" } ] }   // e.g. keep this repo on Claude
      }
    }
  }
}
```

## Resolution order when the repo file is missing

1. `project(action="list")` → match repo/dir name → `project_id`, `identifier`.
2. Trunk: compare `origin/main` vs `origin/develop` ahead/behind counts; the ahead one is trunk.
3. `quality.pre_push`: look for a `quality:pre-push` / `verify` / `check` script in `package.json`,
   else the CI workflow's job commands.
4. `deploy.environments`: the deploy platform (its MCP or CLI), else the CI deploy workflow,
   else the repo's docs.
5. `client`: from the per-user override or the project docs. If no client is configured, skip
   the notify step silently rather than asking.

Write the file once resolved, then proceed. Never block the loop on config discovery. Put
anything private in the per-user override, never in the committed file.
