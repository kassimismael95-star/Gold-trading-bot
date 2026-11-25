# Security policy and deployment controls

## Implemented controls

- Passwords use the configured password-hashing implementation; email OTPs are stored as peppered HMAC digests with expiry, attempt limits and resend cooldown.
- Access and refresh JWTs have bounded lifetimes, a persistent JTI blocklist, and a per-user session version. Password reset increments the session version and invalidates earlier sessions.
- MT5 passwords and EA tokens are AES-GCM encrypted at rest with account-specific associated data. Legacy unbound ciphertext is upgraded after authenticated agent retrieval.
- Ordinary customer account APIs never return MT5 passwords. Credential retrieval requires an enrolled per-agent secret and an account assigned to that agent.
- Oracle enrollment uses the bootstrap `AGENT_SHARED_SECRET` only once; normal requests use the individual agent secret. Agent secrets are stored as hashes server-side and can be rotated by an administrator.
- EA tokens are random, stored hashed and encrypted, scoped to one account, and rotated on reassignment.
- Admin operations, credential changes, commands, refunds, VIP changes, agent rotations, account reassignment and risk-lock resets are audited.
- Flutterwave webhook signatures and provider transaction verification are required before paid entitlements activate. Payment and refund ledger entries are idempotent.
- Production requires explicit CORS origins, PostgreSQL, unique secrets, an encryption key, SMTP and bootstrap admin credentials. Production schema changes use reviewed migrations.
- The EA defaults to demo-only operation and keeps new-entry permission separate from management of existing positions.

## Required operator practices

- Store `APP_SECRET_KEY`, `JWT_SECRET_KEY`, `AGENT_SHARED_SECRET`, `CREDENTIAL_ENCRYPTION_KEY`, Flutterwave keys, SMTP credentials and the bootstrap admin password in deployment secret settings, never in GitHub.
- `CREDENTIAL_ENCRYPTION_KEY` must be URL-safe base64 encoding of 32 random bytes. Back it up securely; losing it makes stored MT5 credentials and EA tokens unrecoverable.
- Keep Oracle agent environment files mode `0600`, `.agent-secret` mode `0600`, and the agent workspace owned by the dedicated `goldagent` user.
- Use HTTPS for all non-local API and agent traffic. Do not expose the credential endpoint to browser clients.
- Verify webhook URLs and merchant permissions in Flutterwave before accepting real payments.
- Keep live trading disabled unless separately reviewed and explicitly enabled by an operator. Start with broker demo accounts.
- Test backup/restore, agent secret rotation, account reassignment, credential revocation and recovery before a live pilot.

## Limitations

This repository has not undergone an independent penetration test, a production security audit, a MetaEditor compile, or live provider/broker integration testing. Per-agent requests use individual secret authentication but do not yet implement signed timestamp/nonce replay protection. Do not treat this project as a certified financial service or a guarantee against loss.

Report vulnerabilities privately to the repository owner.
