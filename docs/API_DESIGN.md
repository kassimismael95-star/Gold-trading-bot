# Database Design

This document defines the full database schema for users, licenses, accounts, bots, orders, positions, workers, and audit logs.

The database must support:

- Self-registration.
- License codes BOSSMODE98 and BOSSMODE99 only.
- Full administrator controls.
- Each customer having their own independent bot, MT5 account, settings, risk, balance, trades, positions and history.
- Different accounts making different BUY, SELL or HOLD decisions.
- Automatic gold symbol detection, including broker-specific suffixes.
- Existing lot-sizing rules and strategy.
- Start, stop, emergency stop and connection monitoring.
- A visible bot signature on MT5 orders where supported.
- Secure handling of MT5 trading passwords.
- Architecture designed for 1,000+ registered and potentially simultaneous accounts, with real capacity testing.

## Core tables

### users

```text
id
email
password_hash
role
is_active
created_at
updated_at
