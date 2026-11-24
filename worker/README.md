# MT5 Worker

This worker runs on a Windows computer or Windows VPS with MetaTrader 5 installed.

It connects to the Render control plane, claims trade commands from the durable queue, executes them through the local MT5 terminal, and reports the result back to Render.

## Requirements

- Windows 10 or Windows 11
- MetaTrader 5 installed
- Python 3.11 or newer
- A broker MT5 account
- The Render control plane URL
- The exact `WORKER_SHARED_SECRET` configured on Render

## Important

Do **not** run this worker against a live trading account until you have:

1. Tested the full flow on a demo account.
2. Confirmed the broker symbol, volume, stop-loss, and take-profit rules.
3. Verified risk limits and reconciliation.
4. Confirmed that only authorized users can create commands.
5. Reviewed all logs and error handling.

This worker can place real trades once connected to a real MT5 account.

## Setup

1. Open Command Prompt on the Windows machine.

2. Create a folder for the worker:

```bat
mkdir boss-mode-worker
cd boss-mode-worker
