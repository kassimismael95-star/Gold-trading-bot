# Gold Scalper Security

This document defines the security rules for the Gold Scalper system.

The system must protect:

- User accounts.
- MT5 trading passwords.
- API secrets.
- EA tokens.
- Admin access.
- Order integrity.
- Audit trails.

## Security principle

Never commit real secrets to GitHub.

Never expose MT5 passwords to the browser.

Never send MT5 passwords through the EA.

Never reuse one worker secret across accounts.

Never allow one customer to access another customer’s data.

## Secrets

Never commit:

```text
SECRET_KEY
DATABASE_URL
WORKER_SHARED_SECRET
MT5_LOGIN
MT5_PASSWORD
MT5_SERVER
