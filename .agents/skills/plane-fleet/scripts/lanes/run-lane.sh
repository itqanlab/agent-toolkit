#!/usr/bin/env bash
# Entry point for fleet lanes and the executor tools.
#   run-lane.sh <codex|opencode> --model <m> --role <role> --ticket <ID> --cwd <dir> \
#               --brief <file> --out <dir> [--sandbox restricted|full|read-only] \
#               [--timeout <sec>] [--effort <level>] [--dry-run] [--ignore-budget]
#   run-lane.sh pick   --role <role> [--kind K] [--triggers a,b] [--urgent] [--attempt N] [--pair-with exe:model]
#   run-lane.sh budget [line|status|check EXE|backoff EXE]
#   run-lane.sh log    add|backfill ... [--set k=v ...] [--from-result <out>/result.json]
#   run-lane.sh stats  [--role R] [--project P]   run-lane.sh report --project P --since ISO   run-lane.sh selftest
#   run-lane.sh cost   [--since ISO] [--ticket T] [--json] [--backfill]   real spend and time per ticket
#   run-lane.sh apply  [--dry-run]           run-lane.sh seed       run-lane.sh models
#   run-lane.sh free-models [list|refresh]    the free models opencode serves today
# Lanes run in run-lane.mjs (node); selection, budget and the log are fleetctl.py (python).
# Docs: executors.md next to this folder.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# nvm installs node and opencode per version; make sure a lane started from a bare
# shell (run_in_background) still finds them.
if ! command -v node >/dev/null 2>&1 || ! command -v opencode >/dev/null 2>&1; then
  for d in "$HOME"/.nvm/versions/node/*/bin; do [ -d "$d" ] && PATH="$d:$PATH"; done
  PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
  export PATH
fi
case "${1:-}" in
  pick|budget|log|stats|report|cost|selftest|apply|seed|config|free-models) exec python3 "$here/fleetctl.py" "$@" ;;
esac
exec node "$here/run-lane.mjs" "$@"
