#!/usr/bin/env bash
# fleet-sweep.sh — find (and with --kill, stop) what fleet sessions left running.
#
# The PM runs it before every spawn and after every report. It reads the repo's slot
# list from .plane/config.json (fleet.slots) and takes the slots that are in use right
# now as an argument, so it never touches a live session's processes.
#
#   scripts/fleet-sweep.sh --repo <repo-root> --live A,C,F          # report only
#   scripts/fleet-sweep.sh --repo <repo-root> --live A,C,F --kill   # stop the leftovers
#
# What counts as a leftover:
#   1. a process listening on the api or client port of a slot that is NOT in --live
#   2. a process whose working directory is a worktree or a slot scratch dir that no longer
#      exists, or a slot scratch dir of a slot not in --live
#   3. an Nx daemon started from any worktree (slots run NX_DAEMON=false, so any daemon
#      under .claude/worktrees is a leftover once its owner is gone; a live slot's daemon
#      is reported, not killed)
#   5. a shell `while pgrep -f X` wait loop older than 1 hour whose target is gone (it
#      matches its own command line and never exits)
#   4. a headless Chromium (Playwright's chrome-headless-shell) whose user-data-dir or cwd
#      belongs to a slot not in --live, or older than --max-browser-hours (default 3)
#
# Slots come from the MERGED config (run-lane.sh config), so per-user extra slots count.
# It also prints the gate. The PM holds spawns when free memory (kern.memorystatus_level,
# the % macOS itself reports) is under --min-free-mem-pct (default 25) or the system disk
# has less than --min-disk-gb (default 6). Swap is shown but not gated on: macOS keeps swap
# allocated long after the memory is free again, so it reads high on a healthy machine.
#
# It never touches processes outside the repo's worktrees and slot dirs (other projects'
# servers are listed under "not ours" so the owner can decide). Exit code: 0 clean,
# 1 leftovers found (or killed), 2 gate closed (memory or disk), 3 usage error.

set -uo pipefail

REPO="" LIVE="" KILL=0 MAX_BROWSER_H=3 MIN_FREE_MEM=25 MIN_DISK=6
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --live) LIVE="$2"; shift 2 ;;
    --kill) KILL=1; shift ;;
    --max-browser-hours) MAX_BROWSER_H="$2"; shift 2 ;;
    --min-free-mem-pct) MIN_FREE_MEM="$2"; shift 2 ;;
    --min-disk-gb) MIN_DISK="$2"; shift 2 ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 3 ;;
  esac
done
[ -n "$REPO" ] && [ -f "$REPO/.plane/config.json" ] || { echo "need --repo <root with .plane/config.json>" >&2; exit 3; }

REPO="$(cd "$REPO" && pwd -P)"
WT="$REPO/.claude/worktrees"
# merged config (repo .plane/config.json plus the per-user override, which may add slots)
CFG="$("$(dirname "$0")/lanes/run-lane.sh" config --cwd "$REPO" 2>/dev/null)"
[ -n "$CFG" ] || CFG="$(cat "$REPO/.plane/config.json")"
# slot scratch dirs are <prefix><slot>; prefix from fleet.slot_scratch_prefix, else
# /tmp/<plane identifier, lowercase>-slot-
SCRATCH="$(jq -r '.fleet.slot_scratch_prefix // empty' <<<"$CFG")"
[ -n "$SCRATCH" ] || SCRATCH="/tmp/$(jq -r '.plane.identifier // "fleet"' <<<"$CFG" | tr A-Z a-z)-slot-"
SCRATCH_BASE="$(basename "$SCRATCH")"
live_has() { case ",$LIVE," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
cwd_of() { lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1; }
# seconds since start, from etime ([[dd-]hh:]mm:ss); macOS ps has no etimes
age_s() { ps -o etime= -p "$1" 2>/dev/null | tr -d ' ' | awk -F'[-:]' '{n=NF; s=$n+$(n-1)*60; if(n>=3)s+=$(n-2)*3600; if(n==4)s+=$1*86400; print s}'; }

LEFT=()   # "pid|reason"
note() { LEFT+=("$1|$2"); }

# 1. slot ports
while IFS=$'\t' read -r slot api client; do
  [ "$slot" = "shared" ] && continue
  live_has "$slot" && continue
  for port in $api $client; do
    for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null); do
      note "$pid" "listening on slot $slot port $port, slot not live"
    done
  done
done < <(jq -r '.fleet.slots | to_entries[] | [.key, (.value.api // ""), (.value.client // "")] | @tsv' <<<"$CFG")

# 2 + 3 + 4. walk node and chromium processes once
while read -r pid cmd; do
  cwd="$(cwd_of "$pid")"
  case "$cwd" in
    "$WT"/*|"$SCRATCH"*|/private"$SCRATCH"*) ;;
    *) continue ;;
  esac
  if [ ! -d "$cwd" ]; then note "$pid" "cwd gone: $cwd"; continue; fi
  slot="$(printf '%s' "$cwd" | sed -n "s#.*/${SCRATCH_BASE}\([a-z]\).*#\1#p" | tr a-z A-Z)"
  if [ -n "$slot" ] && ! live_has "$slot"; then note "$pid" "in scratch of slot $slot, slot not live"; continue; fi
  case "$cmd" in
    *nx/src/daemon/server/start.js*)
      if [ -z "$LIVE" ]; then note "$pid" "Nx daemon in $cwd (slots run NX_DAEMON=false)";
      else echo "note: Nx daemon $pid in $cwd (a live session may own it; slots should run NX_DAEMON=false)"; fi ;;
    *chrome-headless-shell*)
      a="$(age_s "$pid")"; a="${a:-0}"
      if [ "$a" -gt $((MAX_BROWSER_H*3600)) ]; then note "$pid" "headless Chromium up $((a/3600))h in $cwd"; fi ;;
  esac
done < <(ps -axo pid=,command= | grep -E "node|chrome-headless-shell" | grep -v -- "--type=" | grep -v grep | awk '{pid=$1; $1=""; print pid, $0}')

# Chromium whose user-data-dir names a slot that is not live (cwd may be elsewhere)
while read -r pid cmd; do
  slot="$(printf '%s' "$cmd" | sed -n "s#.*${SCRATCH_BASE}\([a-z]\).*#\1#p" | tr a-z A-Z)"
  [ -n "$slot" ] && ! live_has "$slot" && note "$pid" "headless Chromium for slot $slot, slot not live"
done < <(ps -axo pid=,command= | grep "[c]hrome-headless-shell" | grep -v -- "--type=")

# 5. wait loops that can never end: a shell running `while pgrep -f X` matches its own
#    command line, so it spins forever once X is gone. Flag any older than 1 hour whose
#    target has no other process (2026-10-15: six such loops ran 2.5-4 hours).
while read -r pid; do
  cmd="$(ps -o command= -p "$pid" 2>/dev/null)"
  tgt="$(printf '%s' "$cmd" | sed -n 's/.*while pgrep -f \([^ >;]*\).*/\1/p')"
  [ -n "$tgt" ] || continue
  a="$(age_s "$pid")"; [ "${a:-0}" -gt 3600 ] || continue
  others="$(pgrep -f "$tgt" 2>/dev/null | while read -r q; do ps -o command= -p "$q" 2>/dev/null | grep -q "pgrep -f" || echo "$q"; done)"
  [ -z "$others" ] && note "$pid" "wait loop for '$tgt' up $((a/3600))h, nothing left to wait for"
done < <(ps -axo pid=,command= | grep "while pgrep -f" | grep -v grep | awk '{print $1}')

# report
seen=" "
if [ ${#LEFT[@]} -eq 0 ]; then echo "leftovers: none"; else
  echo "leftovers:"
  for e in "${LEFT[@]}"; do
    pid="${e%%|*}"; why="${e#*|}"; case "$seen" in *" $pid "*) continue ;; esac; seen="$seen$pid "
    printf '  %-7s %s :: %s\n' "$pid" "$why" "$(ps -o command= -p "$pid" 2>/dev/null | cut -c1-90)"
    if [ $KILL -eq 1 ]; then
      kids="$(pgrep -P "$pid" 2>/dev/null)"
      kill $pid $kids 2>/dev/null; sleep 1; kill -9 $pid $kids 2>/dev/null
    fi
  done
  [ $KILL -eq 1 ] && echo "killed the processes above (and their children)"
fi

# other projects' servers, for the owner to decide (never killed)
echo "not ours (listening, outside this repo):"
lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1 && ($1 ~ /node|chrome|vite|python/) {print $2}' | sort -u | while read -r pid; do
  cwd="$(cwd_of "$pid")"; case "$cwd" in "$REPO"*|"$SCRATCH"*|/private"$SCRATCH"*) continue ;; esac
  printf '  %-7s up %-12s %s\n' "$pid" "$(ps -o etime= -p "$pid" | tr -d ' ')" "$cwd"
done

# gate
free_mem=$(sysctl -n kern.memorystatus_level 2>/dev/null || echo 100)
swap_used=$(sysctl -n vm.swapusage | sed -n 's/.*used = \([0-9.]*\)M.*/\1/p')
disk_gb=$(df -g /System/Volumes/Data 2>/dev/null | awk 'NR==2{print $4}'); disk_gb=${disk_gb:-$(df -g / | awk 'NR==2{print $4}')}
echo "gate: free memory ${free_mem}% (min ${MIN_FREE_MEM}), disk ${disk_gb} GB free (min ${MIN_DISK}), swap in use ${swap_used%.*} MB (info only)"
if [ "$free_mem" -lt "$MIN_FREE_MEM" ] || [ "$disk_gb" -lt "$MIN_DISK" ]; then echo "gate: CLOSED, spawn nothing new"; exit 2; fi
echo "gate: open"
[ ${#LEFT[@]} -gt 0 ] && exit 1
exit 0
