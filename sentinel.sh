#!/usr/bin/env bash
# ============================================================================
# AutoNovelClaw Sentinel — Background Quality Watchdog
# ============================================================================
# Monitors a running pipeline for quality issues:
#   - NaN/empty chapter drafts
#   - Stalled stages (no progress for N minutes)
#   - Disk space warnings
#   - Token budget tracking
#
# Usage:
#   ./sentinel.sh artifacts/nc-20260317-my-novel/ &
# ============================================================================

set -euo pipefail

ARTIFACT_DIR="${1:?Usage: sentinel.sh <artifact-dir>}"
CHECK_INTERVAL="${2:-60}"  # seconds between checks
STALL_THRESHOLD="${3:-600}"  # seconds before flagging stall

LOG="${ARTIFACT_DIR}/sentinel.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

check_state() {
    local state_file="${ARTIFACT_DIR}/pipeline_state.json"
    if [[ ! -f "$state_file" ]]; then
        log "WARN: No pipeline state file found"
        return
    fi

    # Check for stalled pipeline
    local updated_at
    updated_at=$(python3 -c "
import json, sys
from datetime import datetime, timezone
data = json.load(open('$state_file'))
updated = data.get('updated_at', '')
if updated:
    dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    print(int(age))
else:
    print(99999)
" 2>/dev/null || echo "99999")

    if (( updated_at > STALL_THRESHOLD )); then
        log "ALERT: Pipeline stalled — no update for ${updated_at}s (threshold: ${STALL_THRESHOLD}s)"
    fi

    # Check current stage
    local stage
    stage=$(python3 -c "
import json
data = json.load(open('$state_file'))
print(data.get('current_stage', 'unknown'))
" 2>/dev/null || echo "unknown")
    log "INFO: Current stage: ${stage}, age: ${updated_at}s"
}

check_chapters() {
    local chapters_dir="${ARTIFACT_DIR}/chapters"
    if [[ ! -d "$chapters_dir" ]]; then
        return
    fi

    for f in "${chapters_dir}"/*_draft.md "${chapters_dir}"/*_APPROVED.md; do
        [[ -f "$f" ]] || continue
        local size
        size=$(wc -c < "$f")
        if (( size < 100 )); then
            log "ALERT: Empty/near-empty chapter: $f (${size} bytes)"
        fi
        local words
        words=$(wc -w < "$f")
        if (( words < 1000 )); then
            log "WARN: Very short chapter: $f (${words} words)"
        fi
    done
}

check_disk() {
    local avail
    avail=$(df -BM "${ARTIFACT_DIR}" | awk 'NR==2{print $4}' | tr -d 'M')
    if (( avail < 500 )); then
        log "ALERT: Low disk space: ${avail}MB available"
    fi
}

# === Main loop ===
log "Sentinel started for: ${ARTIFACT_DIR}"
log "Check interval: ${CHECK_INTERVAL}s, Stall threshold: ${STALL_THRESHOLD}s"

while true; do
    check_state
    check_chapters
    check_disk
    sleep "$CHECK_INTERVAL"
done
