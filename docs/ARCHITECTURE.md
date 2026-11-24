# Gold Scalper Architecture

This document defines the corrected phone-only, cloud-only architecture for the Gold Scalper trading bot.

The user operates everything from an Android phone browser.

The user does not own, borrow, rent, or manually operate a personal computer.

The cloud server is the computer.

## Core principle

The system must preserve the existing Gold Scalper website design and trading strategy.

The original `app.py` is the source of truth for:

- Trading strategy.
- Lot sizing.
- Dynamic SL and TP.
- Burst logic.
- Basket logic.
- Symbol resolution.
- Order signatures.
- Position limits.
- Risk rules.

No replacement strategy engine may silently change trading behavior.

## Cloud-only architecture

```text
Android phone browser
        |
        v
GitHub + GitHub Actions
        |
        +--> Render Free control plane + website + dashboard
        |         |
        |         +--> Supabase PostgreSQL
        |         |
        |         +--> Oracle A1 optional backup / monitoring / staging
        |
        +--> Oracle x86 Linux VM
                  |
                  +--> Wine
                  +--> MetaTrader 5
                  +--> Custom MQL5 EA
                  |
                  +--> Exness / MT5 broker
