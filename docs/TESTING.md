# Gold Scalper Testing

This document defines the full testing plan before live trading.

No live trading until all tests pass and the user explicitly authorizes real-money execution.

## Testing principle

The original `app.py` is the source of truth for trading behavior.

All tests must verify that the rebuilt system preserves:

- Trading strategy.
- Lot sizing.
- Dynamic SL and TP.
- Burst logic.
- Basket logic.
- Symbol resolution.
- Order signatures.
- Position limits.
- Risk rules.

## Test types

Run these test types:

- Unit tests.
- Integration tests.
- Security tests.
- Performance tests.
- Reconciliation tests.
- EA communication tests.
- MT5 demo-account tests.
- Order-execution tests.
- Close-basket tests.
- Emergency-stop tests.
- Worker-capacity tests.
- Symbol-resolution tests.
- License tests.
- Admin-control tests.
- End-to-end tests.

## Unit tests

Test:

- Database models.
- License authentication.
- Worker registry.
- Worker capacity.
- Order routing.
- Duplicate-order protection.
- Bot manager.
- Momentum tracker.
- Dynamic SL/TP.
- MT5 client.
- Command executor.
- Worker API.
- Reconciliation.
- Security.
- Performance.
- Live-trading gate.
- End-to-end control-plane flow.
- Final validation.

## Integration tests

Test:

- User registration.
- License activation.
- MT5 account connection.
- Bot creation.
- Bot start.
- Bot stop.
- Emergency stop.
- Order request.
- Order execution.
- Order close.
- Reconciliation.
- Admin controls.
- Worker assignment.
- Worker capacity.
- Symbol resolution.

## Security tests

Test:

- Password hashing.
- Token validation.
- Admin role enforcement.
- User data isolation.
- Cross-account access prevention.
- Cross-bot access prevention.
- Cross-order access prevention.
- Cross-position access prevention.
- Cross-history access prevention.
- Rate limiting.
- HTTPS enforcement.
- Audit logging.
- Secret rotation.
- MT5 password encryption.
- EA token expiration.
- EA token revocation.

## Performance tests

Test:

- Database query speed.
- API response time.
- EA polling latency.
- Order execution latency.
- Worker capacity.
- Concurrent account load.
- Memory use.
- CPU use.
- Disk use.
- Network use.

## Reconciliation tests

Test:

- Open positions match MT5.
- Closed positions match MT5.
- Order status matches MT5.
- Balance matches MT5.
- Equity matches MT5.
- Margin matches MT5.
- No duplicate orders.
- No missing orders.
- No orphan positions.

## EA communication tests

Test:

- EA can poll.
- EA can authenticate.
- EA can report.
- Token refresh works.
- HTTPS works.
- Control-plane URL is whitelisted.
- Symbol detection works.
- Order execution works.
- Order status is updated.
- Reconciliation works.

## MT5 demo-account tests

Test:

- MT5 installs.
- MT5 connects to broker.
- EA loads.
- EA starts.
- EA polls.
- EA executes demo order.
- Order ticket is returned.
- Order signature is attached where supported.
- Magic number is correct.
- SL is set correctly.
- TP is set correctly.
- Position closes correctly.
- Reconciliation works.

## Order-execution tests

Test:

- BUY order executes.
- SELL order executes.
- Order ticket is returned.
- Order signature is attached where supported.
- Magic number is correct.
- SL is set correctly.
- TP is set correctly.
- Order status is updated.
- Order is stored in the database.

## Close-basket tests

Test:

- Basket close command is received.
- All basket positions are closed.
- Close results are reported.
- Basket state is updated.
- No orphan positions remain.

## Emergency-stop tests

Test:

- Emergency stop command is received.
- New orders are blocked.
- Open positions are closed if configured.
- Bot status is updated.
- Account status is updated.
- Emergency stop is logged.
- Restart is blocked until cleared.

## Worker-capacity tests

Test:

- Worker registration.
- Worker heartbeat.
- Worker capacity.
- Active connection count.
- Account assignment.
- Account release.
- Duplicate assignment prevention.
- Capacity overflow prevention.
- Unhealthy worker quarantine.

## Symbol-resolution tests

Test:

- Requested symbol resolves.
- XAUUSDm resolves if available.
- XAUUSD resolves if available.
- XAUUSDc resolves if available.
- XAUUSDr resolves if available.
- GOLD resolves if available.
- Invalid symbol is rejected.

## License tests

Test:

- BOSSMODE98 activates.
- BOSSMODE99 activates.
- BOSSMODE30D is rejected.
- BOSSMODE01D is rejected.
- Duplicate activation is prevented.
- Expired license is rejected.
- Revoked license is rejected.
- License sharing is prevented.

## Admin-control tests

Test:

- Admin can view all users.
- Admin can view all MT5 accounts.
- Admin can view all bots.
- Admin can start bots.
- Admin can stop bots.
- Admin can trigger emergency stop.
- Admin can view connection state.
- Admin can view worker capacity.
- Admin can view order history.
- Admin can view reconciliation status.
- Admin can manage licenses.
- Admin can disable accounts.
- Admin can rotate secrets.
- Admin can view audit logs.

## End-to-end tests

Test:

- User registers.
- User activates license.
- User connects MT5 account.
- User creates bot.
- User starts bot.
- Bot generates signal.
- Order is routed.
- EA receives command.
- EA executes order.
- EA reports result.
- Order is stored.
- Position is tracked.
- Reconciliation runs.
- Admin can monitor.
- Emergency stop works.

## Live-trading gate

Do not enable real-money execution until:

- All tests pass.
- The Render control plane is deployed.
- Supabase is connected.
- The Oracle x86 MT5 pilot is running.
- The EA is installed.
- The EA connects to the control plane.
- A demo MT5 account executes orders correctly.
- Reconciliation works.
- The user explicitly authorizes live execution.

This architecture does not guarantee profitability.

## Test command

Run tests with:

```bash
pytest -v
