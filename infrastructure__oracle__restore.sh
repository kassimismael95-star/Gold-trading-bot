#!/usr/bin/env bash
set -euo pipefail
: "${BACKUP_FILE:?Set BACKUP_FILE to a reviewed backup archive}"
test -f "$BACKUP_FILE"
# Restore to a staging path first; never overwrite live account data blindly.
mkdir -p /var/lib/gold-agent/restore-staging
tar -xzf "$BACKUP_FILE" -C /var/lib/gold-agent/restore-staging
echo "Staged restore; validate ownership and account state before promotion."
