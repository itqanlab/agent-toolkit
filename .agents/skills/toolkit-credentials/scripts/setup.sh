#!/usr/bin/env sh
# setup.sh — check for what this skill needs, and offer to install what is missing.
#
#   node   required, version 18 or newer. Every script here is written in it.
#
# Usage: scripts/setup.sh [--check] [--yes]
#   --check   report status and exit; never installs anything
#   --yes     install without asking (for non-interactive and agent use)
#
# Nothing is installed without either a confirmation or an explicit --yes, and
# any command needing root is printed in full before it runs.
#
# POSIX sh on purpose: this is the one script that cannot assume Node exists,
# so it must run on a machine where nothing has been set up yet.

set -eu

MIN_MAJOR=18
CHECK_ONLY=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check)   CHECK_ONLY=1; shift;;
    --yes|-y)  ASSUME_YES=1; shift;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

node_major() {
  have node || return 1
  node -p 'process.versions.node.split(".")[0]' 2>/dev/null || return 1
}

report() {
  if ! have node; then
    echo "node     MISSING"
    return 1
  fi
  major="$(node_major || echo 0)"
  if [ "$major" -lt "$MIN_MAJOR" ]; then
    echo "node     TOO OLD — found $(node -v), need v${MIN_MAJOR} or newer"
    return 1
  fi
  echo "node     ok ($(node -v))"
  return 0
}

# Prints the install command for this machine, or nothing if we cannot tell.
install_command() {
  case "$(uname -s)" in
    Darwin)
      have brew && { echo "brew install node"; return; }
      echo ""  # Homebrew itself is missing; handled as the unknown case
      ;;
    Linux)
      have apt-get && { echo "sudo apt-get update && sudo apt-get install -y nodejs npm"; return; }
      have dnf     && { echo "sudo dnf install -y nodejs"; return; }
      have pacman  && { echo "sudo pacman -S --noconfirm nodejs npm"; return; }
      have zypper  && { echo "sudo zypper install -y nodejs"; return; }
      have apk     && { echo "sudo apk add nodejs npm"; return; }
      echo ""
      ;;
    *) echo "";;
  esac
}

manual_instructions() {
  echo "Install Node ${MIN_MAJOR} or newer, then run this again."
  echo
  echo "  Easiest, no admin rights needed — nvm:"
  echo "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
  echo "    then open a new terminal and run:  nvm install --lts"
  echo
  echo "  Or download an installer from:  https://nodejs.org/en/download"
  case "$(uname -s)" in
    Darwin) echo "  Or install Homebrew first (https://brew.sh), then:  brew install node";;
  esac
}

if report; then
  [ "$CHECK_ONLY" -eq 1 ] && exit 0
  echo
  echo "Everything this skill needs is already installed."
  exit 0
fi

[ "$CHECK_ONLY" -eq 1 ] && exit 1

echo
cmd="$(install_command)"

if [ -z "$cmd" ]; then
  manual_instructions
  exit 1
fi

echo "Node is needed and can be installed with:"
echo
echo "    $cmd"
echo

if [ "$ASSUME_YES" -ne 1 ]; then
  # No stdin (an agent running this non-interactively) means we must not hang
  # waiting for an answer that will never come.
  if [ ! -t 0 ]; then
    echo "Not running interactively. Re-run with --yes to install, or run the command above yourself."
    exit 1
  fi
  printf 'Run it now? [y/N] '
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Nothing installed."; exit 1;;
  esac
fi

sh -c "$cmd"

echo
if report; then
  echo
  echo "Done. Node is ready."
else
  echo
  echo "Node still is not usable. The package manager may have installed an older version."
  manual_instructions
  exit 1
fi
