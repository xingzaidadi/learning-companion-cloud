#!/usr/bin/env bash
set -euo pipefail

LABEL="com.ruyi.learning-companion-cloud"
PROJECT="/Users/ruyi/Desktop/ruyi-learning-plan/learning-companion-cloud/learning-companion-cloud"
PLIST="$PROJECT/deploy/mac/$LABEL.plist"
DOMAIN="gui/$(id -u)"
LOG_DIR="$HOME/Library/Logs/learning-companion-cloud"
mkdir -p "$LOG_DIR"

for _ in {1..60}; do
  if launchctl print "$DOMAIN" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  exit 0
fi

launchctl bootstrap "$DOMAIN" "$PLIST" || true
launchctl enable "$DOMAIN/$LABEL" || true
launchctl kickstart -k "$DOMAIN/$LABEL" || true
