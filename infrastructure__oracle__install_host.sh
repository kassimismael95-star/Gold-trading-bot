#!/usr/bin/env bash
set -euo pipefail
if [[ "$(uname -m)" != "x86_64" ]]; then echo "WARNING: MT5 terminal/Wine compatibility on $(uname -m) is not validated; verify architecture support before installing." >&2; fi
if [[ $EUID -ne 0 ]]; then echo "Run as root" >&2; exit 1; fi
apt-get update
apt-get install -y python3 python3-venv python3-pip curl ca-certificates unzip xvfb
install -d -m 700 /opt/gold-agent /var/lib/gold-agent/accounts
