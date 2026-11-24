# MT5 Connector

This document defines the custom MQL5 EA connector design and HTTPS communication protocol.

The EA connects each MT5 account to the Render control plane.

It replaces MetaApi.

## Connector principle

Each MT5 account gets:

- Its own MT5 terminal profile.
- Its own Wine prefix.
- Its own EA instance.
- Its own isolated credentials.
- Its own symbol resolver configuration.
- Its own connection state.
- Its own reconciliation state.

The control plane must never route one account’s orders through another account’s terminal.

## EA responsibilities

The EA must:

- Authenticate using a short-lived signed worker token.
- Poll the control plane for commands.
- Execute BUY, SELL, and CLOSE commands.
- Report fills, rejections, errors, balance, equity, margin, open positions, and connection state.
- Detect the broker-specific gold symbol.
- Attach the bot signature where the broker supports it.
- Never store the central API secret in source code.
- Never accept raw MT5 passwords from the control plane.

## EA command flow

```text
EA -> control plane: POST /ea/poll
control plane -> EA: signed command batch
EA -> MT5: execute order
EA -> control plane: POST /ea/report
control plane -> database: update order, position, account, bot state
