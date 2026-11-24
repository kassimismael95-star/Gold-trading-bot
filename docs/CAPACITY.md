# Gold Scalper Capacity

This document defines the real capacity limits, testing plan, and scale ceiling for the Gold Scalper system.

The system must never assume that free cloud infrastructure can support unlimited MT5 accounts.

## Capacity principle

The backend must enforce its own worker capacity.

It must count active MT5 connections and block or queue new accounts beyond its configured capacity.

The system must never rely on Oracle, Render, Supabase, or any broker to silently allow unlimited accounts.

## Render capacity

Render Free provides:

- 750 free instance hours per workspace per month.
- Enough hours for one always-on web service.
- 512 MB RAM.
- No persistent disk.
- No free background worker.

The existing Render service remains awake because UptimeRobot sends periodic HTTP requests.

Render can host:

- Website.
- Dashboard.
- Public API.
- Control-plane API.
- EA polling API.
- EA reporting API.
- Reconciliation API.
- Health-check endpoint.

Render cannot host MT5.

Render cannot host a second always-on free web service without consuming the same 750-hour monthly allowance.

## UptimeRobot

UptimeRobot must ping:

```text
[https://your-render-app.onrender.com/health](https://your-render-app.onrender.com/health)
