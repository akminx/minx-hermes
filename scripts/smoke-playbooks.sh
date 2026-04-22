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
#   3. The script polls Hermes job state + Minx playbook_runs until the new run is terminal
#
# Caveat: `hermes cron tick` runs ALL due jobs — if a regular cron is due at the
# same moment, it will also fire. Run this when you're NOT near a cron boundary.

set -euo pipefail

JOBS_FILE="${HERMES_HOME:-$HOME/.hermes}/cron/jobs.json"
MINX_DB="${MINX_DB:-$HOME/.minx/data/minx.db}"
SMOKE_WAIT_SECONDS="${SMOKE_WAIT_SECONDS:-600}"

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

playbook_id_for_name() {
  case "$1" in
    daily-review) echo "daily_review" ;;
    wiki-update) echo "wiki_update" ;;
    memory-review) echo "memory_review" ;;
    goal-nudge) echo "goal_nudge" ;;
    weekly-review) echo "weekly_report" ;;
    *)
      echo "ERROR: unknown playbook name: $1" >&2
      return 1
      ;;
  esac
}

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
  echo "Last 20 playbook_runs rows:"
  python3 - "$MINX_DB" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
conn.row_factory = sqlite3.Row
try:
    rows = conn.execute(
        """
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
        LIMIT 20
        """
    ).fetchall()
finally:
    conn.close()

headers = ["id", "playbook_id", "status", "trigger_type", "trigger_ref", "triggered_at", "completed_at", "error"]
widths = {header: len(header) for header in headers}
for row in rows:
    for header in headers:
        widths[header] = max(widths[header], len(str(row[header] or "")))

print("  ".join(header.ljust(widths[header]) for header in headers))
print("  ".join("-" * widths[header] for header in headers))
for row in rows:
    print("  ".join(str(row[header] or "").ljust(widths[header]) for header in headers))
PY
}

max_run_id() {
  local playbook_id="$1"
  python3 - "$MINX_DB" "$playbook_id" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
try:
    row = conn.execute(
        "SELECT COALESCE(MAX(id), 0) FROM playbook_runs WHERE playbook_id = ?",
        (sys.argv[2],),
    ).fetchone()
finally:
    conn.close()

print(int(row[0] or 0))
PY
}

job_last_run_at() {
  local name="$1"
  python3 - "$JOBS_FILE" "$name" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    jobs = json.load(f).get("jobs", [])
for job in jobs:
    if job.get("name") == sys.argv[2]:
        print(job.get("last_run_at") or "")
        sys.exit(0)
sys.exit(1)
PY
}

wait_for_terminal_result() {
  local name="$1"
  local job_id="$2"
  local playbook_id="$3"
  local previous_run_id="$4"
  local previous_last_run_at="$5"

  python3 - "$MINX_DB" "$JOBS_FILE" "$name" "$job_id" "$playbook_id" "$previous_run_id" "$previous_last_run_at" "$SMOKE_WAIT_SECONDS" <<'PY'
import json
import sqlite3
import sys
import time

db_path, jobs_file, name, job_id, playbook_id, previous_run_id_raw, previous_last_run_at, timeout_raw = sys.argv[1:9]
previous_run_id = int(previous_run_id_raw)
timeout_seconds = int(timeout_raw)
deadline = time.monotonic() + timeout_seconds

def load_job_state():
    with open(jobs_file, encoding="utf-8") as f:
        jobs = json.load(f).get("jobs", [])
    for job in jobs:
        if job.get("id") == job_id:
            return {
                "last_run_at": job.get("last_run_at"),
                "last_status": job.get("last_status"),
                "last_error": job.get("last_error"),
            }
    raise SystemExit(f"ERROR: job disappeared from jobs.json: {name} ({job_id})")

def load_new_run():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, status, triggered_at, completed_at, error_message
            FROM playbook_runs
            WHERE playbook_id = ? AND id > ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (playbook_id, previous_run_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)

while time.monotonic() < deadline:
    job = load_job_state()
    run = load_new_run()
    job_started = bool(job["last_run_at"]) and job["last_run_at"] != (previous_last_run_at or None)

    if job_started and job["last_status"] == "error":
        error_text = job["last_error"] or "unknown Hermes cron error"
        print(f"  ✗ Hermes job failed: {error_text}")
        raise SystemExit(2)

    if run is not None and run["status"] in {"succeeded", "skipped", "failed"}:
        print(f"  audit row: id={run['id']} status={run['status']} triggered_at={run['triggered_at']}")
        if run["completed_at"]:
            print(f"  completed_at: {run['completed_at']}")
        if run["error_message"]:
            print(f"  error: {run['error_message']}")
        if run["status"] == "failed":
            raise SystemExit(3)
        if job_started and job["last_status"] not in (None, "ok"):
            print(f"  ✗ Hermes job status unexpected: {job['last_status']}")
            raise SystemExit(4)
        raise SystemExit(0)

    time.sleep(2)

job = load_job_state()
run = load_new_run()
if run is None and job.get("last_status") == "ok":
    print("  ✗ Hermes job completed but no new terminal playbook_runs row was recorded")
else:
    print(
        "  ✗ timed out waiting for terminal result "
        f"(job.last_status={job.get('last_status')}, new_run={'yes' if run else 'no'})"
    )
raise SystemExit(5)
PY
}

run_one() {
  local name="$1"
  local job_id
  local playbook_id
  local previous_run_id
  local previous_last_run_at
  if ! job_id=$(lookup_job_id "$name" 2>/dev/null); then
    echo "  ✗ $name — not found in jobs.json"
    return 1
  fi
  if ! playbook_id=$(playbook_id_for_name "$name"); then
    return 1
  fi
  previous_run_id="$(max_run_id "$playbook_id")"
  previous_last_run_at="$(job_last_run_at "$name")"

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

  echo "  queued; waiting for terminal audit row..."
  if ! wait_for_terminal_result "$name" "$job_id" "$playbook_id" "$previous_run_id" "$previous_last_run_at"; then
    return 1
  fi

  echo "  ✓ terminal status recorded"
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
