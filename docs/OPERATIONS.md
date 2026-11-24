# Gold Scalper Operations

This document defines day-to-day operations, monitoring, recovery, and incident response from an Android phone browser.

No local computer is required for management.

## Operations principle

All management must be possible from an Android phone browser.

The cloud server is the computer.

The user does not own, borrow, rent, or manually operate a personal computer.

## Daily operations

Check:

- Render service health.
- Supabase database health.
- Oracle A1 backup status.
- Oracle x86 MT5 pilot status.
- EA connection status.
- Worker heartbeat.
- Active MT5 connections.
- Bot status.
- Open positions.
- Recent orders.
- Reconciliation status.
- Error logs.
- Audit logs.

## Monitoring

Monitor:

- Render service uptime.
- Supabase database uptime.
- Oracle A1 uptime.
- Oracle x86 MT5 pilot uptime.
- EA connection status.
- Worker heartbeat.
- Active MT5 connections.
- Bot status.
- Open positions.
- Recent orders.
- Reconciliation status.
- Error logs.
- Audit logs.

Use UptimeRobot to keep the Render service awake.

Use Render logs to monitor application errors.

Use Supabase logs to monitor database errors.

Use Oracle logs to monitor server errors.

## Recovery

If a service fails:

1. Check Render logs.
2. Check Supabase logs.
3. Check Oracle logs.
4. Identify the failure.
5. Restart the affected service.
6. Verify recovery.
7. Run reconciliation.
8. Review audit logs.
9. Notify administrator if needed.

## Incident response

If a secret is exposed:

1. Rotate the secret immediately.
2. Revoke affected tokens.
3. Disable affected accounts.
4. Review audit logs.
5. Notify administrators.
6. Patch the vulnerability.
7. Re-run security tests.

If MT5 disconnects:

1. Check EA connection status.
2. Check worker heartbeat.
3. Check Oracle x86 MT5 pilot status.
4. Check broker connection.
5. Restart MT5 if needed.
6. Run reconciliation.
7. Review audit logs.

If reconciliation fails:

1. Check order status.
2. Check position status.
3. Check balance.
4. Check equity.
5. Check margin.
6. Check worker heartbeat.
7. Check EA connection.
8. Re-run reconciliation.
9. Review audit logs.

## Emergency stop

Emergency stop must:

- Stop new orders immediately.
- Close open positions if configured.
- Mark the bot as stopped.
- Mark the account as emergency-stopped.
- Prevent restart until an administrator clears the emergency stop.
- Log the action.
- Notify the administrator.

## Backup

Backups must:

- Be encrypted.
- Be stored securely.
- Be access-controlled.
- Be tested for restore.
- Never contain plain-text MT5 passwords.
- Never contain plain-text API secrets.

Backup schedule:

```text
Daily database backup
Weekly full backup
Monthly archive backup
