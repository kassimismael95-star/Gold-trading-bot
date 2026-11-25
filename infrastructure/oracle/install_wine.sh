#!/usr/bin/env bash
set -euo pipefail
# MT5/Wine compatibility varies by host image. Verify vendor-supported setup first.
apt-get update
apt-get install -y wine wine64 winetricks
wine --version
