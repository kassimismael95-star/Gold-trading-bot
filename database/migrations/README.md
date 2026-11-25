# PostgreSQL migration order

Back up the database and verify the target schema first.

For a **fresh database**, apply the numbered SQL files in order from `0001_initial_schema.sql` through `0021_account_soft_delete.sql` using `psql` or your migration runner.

1. `0001_initial_schema.sql` — original core schema
2. `0002_command_ack_and_account_heartbeat.sql` — command results and account heartbeat
3. `0003_wallet_ledger.sql` — wallet ledger, balance snapshots, reconciliation, webhooks, refunds and disputes
4. `0004_account_credential_vault.sql` — encrypted broker credential and EA-token ciphertext
5. `0005_email_verification_challenges.sql` — email verification state and OTP challenges
6. `0006_audit_and_rate_limit.sql` — audit trail and persistent rate limiter
7. `0007_subscription_lifecycle.sql` — payment-linked subscriptions
8. `0008_session_revocation.sql` — JWT revocation blocklist
9. `0009_agent_identity_secrets.sql` — per-agent credential hashes
10. `0010_account_risk_settings.sql` — validated account-level risk settings
11. `0011_account_telemetry.sql` — latest MT5 account telemetry
12. `0012_account_token_version.sql` — EA token rotation version
13. `0013_account_event_idempotency.sql` — deduplicated trade-deal history
14. `0014_payment_provider_id_unique.sql` — one internal payment per provider transaction
15. `0015_merchant_wallet_currency_unique.sql` — one merchant ledger wallet per currency
16. `0016_user_session_version.sql` — revoke all sessions after password reset
17. `0017_agent_capacity.sql` — configured per-agent account capacity
18. `0018_agent_resource_metrics.sql` — resource-based effective capacity telemetry
19. `0019_account_telemetry_connection.sql` — broker connection state in account telemetry
20. `0020_wallet_reconciliation_snapshot_link.sql` — link provider balance differences to snapshots
21. `0021_account_soft_delete.sql` — safe account removal after EA reports connected and flat

For an existing installation, **do not replay migration 0001**. Inspect the live schema, identify exactly which changes already exist, baseline/reconcile migration history, and apply only the missing safe changes. These files use PostgreSQL SQL types and syntax.

Production API startup does not call `create_all()` unless `AUTO_CREATE_DB=true` is explicitly set. Keep it false in production and use reviewed migrations.
