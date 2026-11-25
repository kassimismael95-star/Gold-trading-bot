#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Run as root" >&2; exit 1; fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
: "${AGENT_ENV_FILE:=/etc/gold-agent.env}"
: "${AGENT_INSTALL_DIR:=/opt/gold-agent}"
: "${AGENT_USER:=goldagent}"
if [[ ! "$AGENT_ENV_FILE" =~ ^[A-Za-z0-9_./-]+$ || ! "$AGENT_INSTALL_DIR" =~ ^[A-Za-z0-9_./-]+$ ]]; then echo "Agent install/env paths must not contain shell or sed metacharacters" >&2; exit 1; fi
if [[ ! -f "$AGENT_ENV_FILE" ]]; then echo "Create $AGENT_ENV_FILE from gold-agent.env.example and set API_BASE_URL, agent bootstrap/per-agent secret, MT5_INSTALL_DIR, EA_SOURCE_DIR, MT5_LAUNCH_COMMAND and METAEDITOR_COMMAND." >&2; exit 1; fi
id "$AGENT_USER" >/dev/null 2>&1 || useradd --system --home /var/lib/gold-agent --create-home --shell /usr/sbin/nologin "$AGENT_USER"
install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 700 /var/lib/gold-agent /var/lib/gold-agent/accounts "$AGENT_INSTALL_DIR"
install -d -m 755 /opt/gold-trading-bot/trading/ea
cp -a "$REPO_ROOT/trading/ea/." /opt/gold-trading-bot/trading/ea/
# Copy the actual checked-out agent source with its relative module paths intact.
cp -a "$REPO_ROOT/services/oracle-agent/." "$AGENT_INSTALL_DIR/"
python3 -m venv "$AGENT_INSTALL_DIR/venv"
"$AGENT_INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$AGENT_INSTALL_DIR/venv/bin/pip" install -r "$AGENT_INSTALL_DIR/requirements.txt"
chown -R "$AGENT_USER:$AGENT_USER" "$AGENT_INSTALL_DIR" /var/lib/gold-agent
chmod 600 "$AGENT_ENV_FILE"
sed -e "s|/etc/gold-agent.env|$AGENT_ENV_FILE|g" \
    -e "s|/opt/gold-agent|$AGENT_INSTALL_DIR|g" \
    -e "s|User=goldagent|User=$AGENT_USER|g" \
    -e "s|Group=goldagent|Group=$AGENT_USER|g" \
    "$SCRIPT_DIR/gold-agent.service" > /etc/systemd/system/gold-agent.service
chmod 644 /etc/systemd/system/gold-agent.service
systemctl daemon-reload
systemctl enable gold-agent.service
echo "Agent installed and enabled. Verify MT5_INSTALL_DIR and MetaEditor paths, then run: systemctl start gold-agent.service"
