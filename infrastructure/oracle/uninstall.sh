#!/usr/bin/env bash
set -euo pipefail
systemctl stop gold-agent.service 2>/dev/null || true
systemctl disable gold-agent.service 2>/dev/null || true
rm -f /etc/systemd/system/gold-agent.service
systemctl daemon-reload
# Account data and secrets are intentionally retained for explicit backup/removal.
