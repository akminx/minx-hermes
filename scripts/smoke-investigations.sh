#!/usr/bin/env bash
# Slice 9 investigation smoke helper.
#
# Usage:
#   ./scripts/smoke-investigations.sh --history
#   ./scripts/smoke-investigations.sh --check-schema
#   ./scripts/smoke-investigations.sh -- <command that triggers minx_investigate>
#
# The command form snapshots max(investigations.id), runs the supplied command
# without eval, then waits for a new terminal investigations row.

set -euo pipefail

MINX_DB="${MINX_DB:-$HOME/.minx/data/minx.db}"
SMOKE_WAIT_SECONDS="${SMOKE_WAIT_SECONDS:-600}"

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing required command: $1" >&2; exit 1; }
}

require python3

cmd_history() {
  echo "Last 20 investigations rows:"
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
          kind,
          harness,
          status,
          tool_call_count,
          substr(started_at, 1, 19) AS started_at,
          substr(COALESCE(completed_at, ''), 1, 19) AS completed_at,
          substr(COALESCE(error_message, ''), 1, 60) AS error
        FROM investigations
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()
finally:
    conn.close()

headers = ["id", "kind", "harness", "status", "tool_call_count", "started_at", "completed_at", "error"]
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

cmd_check_schema() {
  python3 - "$MINX_DB" <<'PY'
import sqlite3
import sys

required = {
    "id",
    "harness",
    "kind",
    "question",
    "context_json",
    "status",
    "answer_md",
    "trajectory_json",
    "response_template",
    "response_slots_json",
    "citation_refs_json",
    "tool_call_count",
    "token_input",
    "token_output",
    "cost_usd",
    "started_at",
    "completed_at",
    "error_message",
}

conn = sqlite3.connect(sys.argv[1])
try:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'investigations'"
    ).fetchone()
    if row is None:
        raise SystemExit("ERROR: investigations table does not exist")
    columns = {item[1] for item in conn.execute("PRAGMA table_info(investigations)").fetchall()}
finally:
    conn.close()

missing = sorted(required - columns)
if missing:
    raise SystemExit(f"ERROR: investigations table missing columns: {', '.join(missing)}")
print("investigations schema OK")
PY
}

max_investigation_id() {
  python3 - "$MINX_DB" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
try:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM investigations").fetchone()
finally:
    conn.close()
print(int(row[0] or 0))
PY
}

wait_for_terminal_investigation() {
  local previous_id="$1"
  python3 - "$MINX_DB" "$previous_id" "$SMOKE_WAIT_SECONDS" <<'PY'
import json
import re
import sqlite3
import sys
import time

db_path, previous_id_raw, timeout_raw = sys.argv[1:4]
previous_id = int(previous_id_raw)
timeout_seconds = int(timeout_raw)
deadline = time.monotonic() + timeout_seconds
terminal = {"succeeded", "failed", "cancelled", "budget_exhausted"}
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_KEYS = {
    "raw",
    "raw_output",
    "output",
    "result",
    "response",
    "messages",
    "transcript",
    "rows",
    "transactions",
}

def load_new_run():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT
              id,
              kind,
              harness,
              status,
              started_at,
              completed_at,
              error_message,
              tool_call_count,
              trajectory_json,
              citation_refs_json
            FROM investigations
            WHERE id > ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (previous_id,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else dict(row)

def validate_terminal_run(run):
    trajectory = json.loads(run["trajectory_json"] or "[]")
    if not isinstance(trajectory, list):
        raise SystemExit("ERROR: trajectory_json is not a list")
    # Empty trajectory is legitimate for failed/cancelled runs (e.g. start
    # succeeded but the first domain call failed before we could append).
    if run["status"] in {"succeeded", "budget_exhausted"} and not trajectory:
        raise SystemExit(
            "ERROR: terminal investigation has no trajectory steps for "
            f"status={run['status']}"
        )

    for index, step in enumerate(trajectory, start=1):
        if not isinstance(step, dict):
            raise SystemExit(f"ERROR: trajectory step {index} is not an object")
        for key in ("args_digest", "result_digest"):
            if not DIGEST_RE.match(str(step.get(key, ""))):
                raise SystemExit(f"ERROR: trajectory step {index} has invalid {key}")
        event_slots = step.get("event_slots", {})
        if isinstance(event_slots, dict) and FORBIDDEN_KEYS.intersection(event_slots):
            raise SystemExit(
                f"ERROR: trajectory step {index} stores raw-output-like event_slots keys"
            )

    citations = json.loads(run["citation_refs_json"] or "[]")
    if citations and not isinstance(citations, list):
        raise SystemExit("ERROR: citation_refs_json is not a list")

while time.monotonic() < deadline:
    run = load_new_run()
    if run is not None and run["status"] in terminal:
        validate_terminal_run(run)
        print(
            "  investigation row: "
            f"id={run['id']} kind={run['kind']} status={run['status']} "
            f"tool_call_count={run['tool_call_count']}"
        )
        if run["completed_at"]:
            print(f"  completed_at: {run['completed_at']}")
        if run["error_message"]:
            print(f"  error: {run['error_message']}")
        if run["status"] in {"failed", "cancelled"}:
            raise SystemExit(3)
        raise SystemExit(0)
    time.sleep(2)

run = load_new_run()
print(f"  timed out waiting for terminal investigation row (new_run={'yes' if run else 'no'})")
raise SystemExit(5)
PY
}

main() {
  case "${1:-}" in
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    --history)
      cmd_history
      exit 0
      ;;
    --check-schema)
      cmd_check_schema
      exit 0
      ;;
    --)
      shift
      ;;
    "")
      echo "ERROR: provide --history, --check-schema, or -- <command>" >&2
      exit 2
      ;;
  esac

  if [[ $# -eq 0 ]]; then
    echo "ERROR: missing command after --" >&2
    exit 2
  fi

  cmd_check_schema
  local previous_id
  previous_id="$(max_investigation_id)"

  echo "Slice 9 investigation smoke"
  echo "DB: $MINX_DB"
  echo "Previous max investigation id: $previous_id"
  echo "Running command: $*"

  "$@"

  echo "Waiting for terminal investigation row..."
  wait_for_terminal_investigation "$previous_id"
  echo "Done. Terminal investigation status recorded."
}

main "$@"
