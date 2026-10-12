#!/usr/bin/env sh
# setup-deps.sh — check for what this skill needs, and offer to install what is missing.
#
#   node         required, version 18 or newer. The guard script is written in it.
#   higgsfield   required. The official Higgsfield command line tool (npm @higgsfield/cli).
#
# Usage: scripts/setup-deps.sh [--check] [--yes]
#   --check   report status and exit; never installs anything
#   --yes     install without asking (for non-interactive and agent use)
#
# Nothing is installed without either a confirmation or an explicit --yes, and every
# command is printed in full before it runs. Signing in is not done here: the user runs
# `higgsfield auth login` once, which opens the browser.
#
# POSIX sh on purpose: this is the one script that cannot assume Node exists.

set -eu

MIN_MAJOR=18
CHECK_ONLY=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check)   CHECK_ONLY=1; shift;;
    --yes|-y)  ASSUME_YES=1; shift;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

node_ok() {
  have node || return 1
  major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  [ "$major" -ge "$MIN_MAJOR" ]
}

report() {
  ok=0
  if ! have node; then echo "node         MISSING"; ok=1
  elif ! node_ok; then echo "node         TOO OLD, found $(node -v), need v${MIN_MAJOR} or newer"; ok=1
  else echo "node         ok ($(node -v))"; fi
  if have higgsfield; then echo "higgsfield   ok ($(higgsfield version 2>/dev/null | head -1))"
  else echo "higgsfield   MISSING"; ok=1; fi
  return $ok
}

ask() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  # No stdin (an agent running this) means no one can answer, so do not hang.
  if [ ! -t 0 ]; then
    echo "Not running interactively. Re-run with --yes to install, or run the command above yourself."
    return 1
  fi
  printf 'Run it now? [y/N] '
  read -r answer
  case "$answer" in y|Y|yes|YES) return 0;; *) echo "Nothing installed."; return 1;; esac
}

if report; then
  [ "$CHECK_ONLY" -eq 1 ] && exit 0
  echo
  echo "Everything this skill needs is installed. If you have not signed in yet, run:"
  echo "    higgsfield auth login"
  exit 0
fi
[ "$CHECK_ONLY" -eq 1 ] && exit 1
echo

if ! node_ok; then
  echo "Node ${MIN_MAJOR} or newer is needed first."
  echo "  Easiest, no admin rights needed (nvm):"
  echo "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
  echo "    then open a new terminal and run:  nvm install --lts"
  echo "  Or download an installer from:  https://nodejs.org/en/download"
  [ "$(uname -s)" = Darwin ] && echo "  Or with Homebrew:  brew install node"
  echo "Then run this again."
  exit 1
fi

# npm is the one install route that works on macOS, Linux and Windows alike.
# Higgsfield's own installer is the alternative on macOS and Linux:
#   curl -fsSL https://raw.githubusercontent.com/higgsfield-ai/cli/main/install.sh | sh
cmd="npm install -g @higgsfield/cli"
echo "The Higgsfield command line tool can be installed with:"
echo
echo "    $cmd"
echo
ask || exit 1
sh -c "$cmd"

echo
if report; then
  echo
  echo "Done. Now sign in once (it opens the browser):"
  echo "    higgsfield auth login"
else
  echo
  echo "higgsfield is still not on the PATH. Open a new terminal and run this again."
  exit 1
fi
