#!/usr/bin/env bash
# daily.sh — local daily runner (macOS, cron or launchd).
#
# Auto-discovers finished WC2026 matches from SofaScore over the last few days,
# scrapes any new ones, rebuilds the processed parquet, writes a dated snapshot,
# commits, and pushes. The Dash app then reads the updated parquet/JSON.
#
# Idempotent: matches already scraped are skipped; missed days self-heal because
# a finished match's momentum series never changes.
#
# Usage (manual):
#   bash scripts/daily.sh
#
# Cron (run at 09:00 every day):
#   0 9 * * * /usr/bin/env bash /path/to/wc-rafael/scripts/daily.sh >> /path/to/wc-rafael/logs/daily.log 2>&1
#
# launchd alternative:
#   See reports/automation.md for a LaunchAgent plist template.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

TODAY="$(date +%Y-%m-%d)"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"

HEARTBEAT_FILE="$LOG_DIR/last_run.json"
LOG_FILE="$LOG_DIR/daily.log"

log() {
    local ts
    ts="$(date '+%Y-%m-%dT%H:%M:%S')"
    echo "$ts  $*" | tee -a "$LOG_FILE"
}

heartbeat() {
    local status="$1"
    local note="$2"
    printf '{"time":"%s","date":"%s","status":"%s","note":"%s"}\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$TODAY" "$status" "$note" \
        > "$HEARTBEAT_FILE"
}

# Resolve uv: try PATH first, then the common install location on macOS.
if command -v uv &>/dev/null; then
    UV="uv"
elif [ -f "$HOME/.local/bin/uv" ]; then
    UV="$HOME/.local/bin/uv"
elif [ -f "$HOME/.cargo/bin/uv" ]; then
    UV="$HOME/.cargo/bin/uv"
else
    log "ERROR: uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    heartbeat "FAIL" "uv not found"
    exit 1
fi

log "[daily] $TODAY — discover + scrape + build"

# ── pipeline steps ────────────────────────────────────────────────────────────
if ! "$UV" run python -m src.pipeline \
        --discover-days 3 \
        --ids-file data/match_ids.json \
        --date "$TODAY"; then
    heartbeat "FAIL" "pipeline failed"
    log "[daily] FAILED: pipeline step"
    exit 1
fi

log "[daily] pipeline complete"

# ── commit only derived data (raw is gitignored) ──────────────────────────────
git add data/processed snapshots data/match_ids.json

CHANGED="$(git status --porcelain data/processed snapshots data/match_ids.json)"
if [ -n "$CHANGED" ]; then
    git commit -m "data: daily update $TODAY"

    # Best-effort push: only if an 'origin' remote exists.
    if git remote 2>/dev/null | grep -q '^origin$'; then
        if git push; then
            log "[daily] pushed $TODAY"
            heartbeat "OK" "pushed"
        else
            log "[daily] push failed; retrying in 10s"
            sleep 10
            if git push; then
                log "[daily] pushed $TODAY (retry)"
                heartbeat "OK" "pushed (retry)"
            else
                log "[daily] push failed twice — data committed locally"
                heartbeat "PUSH_FAIL" "git push failed twice"
            fi
        fi
    else
        log "[daily] committed $TODAY (no 'origin' remote — skipping push)"
        heartbeat "OK" "committed, no remote"
    fi
else
    log "[daily] no changes to commit"
    heartbeat "OK" "no changes"
fi
