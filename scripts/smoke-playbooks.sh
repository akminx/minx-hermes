#!/usr/bin/env bash
# Slice 8 playbook smoke tests — imperatively pings each minx playbook cron job.
#
# Usage:
#   ./smoke-playbooks.sh                    # run all 5 playbooks
#   ./smoke-playbooks.sh daily-review       # run just one
#   ./smoke-playbooks.sh daily-review wiki-update
#   ./smoke-playbooks.sh --list             # list job IDs, don't run
#   ./smoke-playbooks.sh --history          # show recent playbook_runs (requires sqlite3)
#
# How it works:
#   1. Each selected job is queued via `hermes cron run <job_id>` (flips next_run_at=now)
#   2. Then `hermes cron tick` fires all due jobs once
#   3. Between runs, the script sleeps briefly so runs don't overlap
#
# Caveat: `hermes cron tick` runs ALL due jobs — if a regular cron is due at the
# same moment, it will also fire. Run this when you're NOT near a cron boundary.

set -euo pipefail

JOBS_FILE="${HERMES_HOME:-$HOME/.hermes}/cron/jobs.json"
MINX_DB="${MINX_DB:-$HOME/.minx/data/minx.db}"

# Playbooks in dependency-friendly order.
ALL_PLAYBOOKS=(
  daily-review
  wiki-update
  memory-review
  goal-nudge
  weekly-review
)

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing required command: $1" >&2; exit 1; }
}

require hermes
require python3

lookup_job_id() {
  local name="$1"
  python3 - "$JOBS_FILE" "$name" <<'PY'
import json, sys
path, name = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
for job in data.get("jobs", []):
    if job.get("name") == name:
        print(job["id"])
        sys.exit(0)
sys.exit(1)
PY
}

cmd_list() {
  printf "%-20s %s\n" "NAME" "JOB_ID"
  printf "%-20s %s\n" "----" "------"
  for name in "${ALL_PLAYBOOKS[@]}"; do
    if id=$(lookup_job_id "$name" 2>/dev/null); then
      printf "%-20s %s\n" "$name" "$id"
    else
      printf "%-20s %s\n" "$name" "(not in jobs.json)"
    fi
  done
}

cmd_history() {
  require sqlite3
  echo "Last 20 playbook_runs rows:"
  sqlite3 -header -column "$MINX_DB" "
    SELECT
      id,
      playbook_id,
      status,
      trigger_type,
      substr(COALESCE(trigger_ref, ''), 1, 24) AS trigger_ref,
      substr(triggered_at, 1, 19) AS triggered_at,
      substr(COALESCE(completed_at, ''), 1, 19) AS completed_at,
      substr(COALESCE(error_message, ''), 1, 60) AS error
    FROM playbook_runs
    ORDER BY id DESC
    LIMIT 20;
  "
}

run_one() {
  local name="$1"
  local job_id
  if ! job_id=$(lookup_job_id "$name" 2>/dev/null); then
    echo "  ✗ $name — not found in jobs.json"
    return 1
  fi

  echo ""
  echo "▶ Running: $name ($job_id)"

  if ! hermes cron run "$job_id" >/dev/null; then
    echo "  ✗ failed to queue"
    return 1
  fi

  if ! hermes cron tick; then
    echo "  ✗ tick failed"
    return 1
  fi

  echo "  ✓ queued and ticked"

  # Give the scheduler a moment to hand off the job before the next iteration,
  # so overlapping playbook_runs don't confuse playbook_history.
  sleep 3
}

main() {
  local targets=()

  if [[ $# -eq 0 ]]; then
    targets=("${ALL_PLAYBOOKS[@]}")
  else
    case "$1" in
      -h|--help)
        sed -n '2,18p' "$0" | sed 's/^# \?//'
        exit 0
        ;;
      --list)
        cmd_list
        exit 0
        ;;
      --history)
        cmd_history
        exit 0
        ;;
      *)
        targets=("$@")
        ;;
    esac
  fi

  echo "Slice 8 playbook smoke — targets: ${targets[*]}"
  echo "Jobs file: $JOBS_FILE"
  echo ""

  local failed=0
  for name in "${targets[@]}"; do
    # Validate it's one of ours before touching hermes.
    local valid=0
    for allowed in "${ALL_PLAYBOOKS[@]}"; do
      [[ "$name" == "$allowed" ]] && { valid=1; break; }
    done
    if [[ $valid -eq 0 ]]; then
      echo "  ✗ $name — not a minx playbook (allowed: ${ALL_PLAYBOOKS[*]})"
      failed=$((failed + 1))
      continue
    fi

    if ! run_one "$name"; then
      failed=$((failed + 1))
    fi
  done

  echo ""
  if [[ $failed -gt 0 ]]; then
    echo "Done. $failed of ${#targets[@]} failed to queue/tick."
    exit 1
  fi

  echo "Done. All ${#targets[@]} queued and ticked."
  echo ""
  echo "Inspect results:"
  echo "  $0 --history"
  echo "  hermes cron status"
}

main "$@"
