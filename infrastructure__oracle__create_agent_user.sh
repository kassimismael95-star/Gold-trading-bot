#!/usr/bin/env bash
set -euo pipefail
id goldagent >/dev/null 2>&1 || useradd --system --home /var/lib/gold-agent --create-home --shell /usr/sbin/nologin goldagent
install -d -o goldagent -g goldagent -m 700 /var/lib/gold-agent/accounts
