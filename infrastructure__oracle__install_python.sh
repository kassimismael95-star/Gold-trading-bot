#!/usr/bin/env bash
set -euo pipefail
python3 -m venv /opt/gold-agent/venv
/opt/gold-agent/venv/bin/pip install --upgrade pip
/opt/gold-agent/venv/bin/pip install -r "$(dirname "$0")/../../services/oracle-agent/requirements.txt"
