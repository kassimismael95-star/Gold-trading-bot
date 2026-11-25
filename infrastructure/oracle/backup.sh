#!/usr/bin/env bash
set -euo pipefail
: "${BACKUP_DIR:=/var/backups/gold-agent}"
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
tar --exclude='*.log' -czf "$BACKUP_DIR/accounts-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" /var/lib/gold-agent/accounts
