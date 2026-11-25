#!/usr/bin/env bash
set -euo pipefail
: "${MT5_INSTALLER_URL:?Set MT5_INSTALLER_URL to a legitimate vendor-provided installer URL}"
: "${MT5_INSTALL_DIR:=/opt/mt5}"
install -d -m 755 "$MT5_INSTALL_DIR"
curl --fail --location --proto '=https' --tlsv1.2 "$MT5_INSTALLER_URL" -o "$MT5_INSTALL_DIR/mt5-installer.exe"
echo "Installer downloaded. Run and verify installation interactively; this script does not claim MT5 is installed."
