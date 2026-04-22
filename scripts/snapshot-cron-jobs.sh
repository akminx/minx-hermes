#!/usr/bin/env bash
# Snapshot the 5 Minx playbook cron jobs from ~/.hermes/cron/jobs.json
# into a clean, deterministic JSON file in this repo for version control.
#
# Volatile runtime fields (last_run_at, next_run_at, state, etc.) are stripped
# so diffs only reflect actual config changes.
#
# Usage:
#   ./snapshot-cron-jobs.sh
#
# Output: <repo-root>/cron/jobs.snapshot.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

JOBS_FILE="${HERMES_HOME:-$HOME/.hermes}/cron/jobs.json"
OUT_FILE="$REPO_ROOT/cron/jobs.snapshot.json"

if [[ ! -f "$JOBS_FILE" ]]; then
  echo "ERROR: cron jobs file not found: $JOBS_FILE" >&2
  exit 1
fi

python3 - "$JOBS_FILE" "$OUT_FILE" <<'PY'
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

PLAYBOOK_NAMES = {
    "daily-review",
    "wiki-update",
    "memory-review",
    "goal-nudge",
    "weekly-review",
}

VOLATILE_TOP = {
    "last_run_at",
    "last_status",
    "last_error",
    "last_delivery_error",
    "next_run_at",
    "paused_at",
    "paused_reason",
    "state",
}

data = json.loads(src.read_text())
jobs = data.get("jobs", data) if isinstance(data, dict) else data

selected = []
for job in jobs:
    if job.get("name") not in PLAYBOOK_NAMES:
        continue
    clean = {k: v for k, v in job.items() if k not in VOLATILE_TOP}
    # strip repeat.completed if present
    repeat = clean.get("repeat")
    if isinstance(repeat, dict) and "completed" in repeat:
        repeat = {k: v for k, v in repeat.items() if k != "completed"}
        clean["repeat"] = repeat
    selected.append(clean)

selected.sort(key=lambda j: j.get("name", ""))

dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps({"jobs": selected}, indent=2, sort_keys=True) + "\n")
print(f"wrote {len(selected)} job(s) to {dst}")
PY
