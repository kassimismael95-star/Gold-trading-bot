#!/usr/bin/env bash
set -euo pipefail
python3 --version
if [[ -d /var/lib/gold-agent/accounts ]]; then echo "workspace=present"; else echo "workspace=missing"; exit 1; fi
