#!/usr/bin/env bash
# Old path of the fleet command (before 2.0.0), kept for one version so existing sessions and notes still work.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../core/scripts/fleet" "$@"
