# Render deployment checklist

- Configure PostgreSQL and take a backup before migrations.
- Set unique random APP_SECRET_KEY and JWT_SECRET_KEY.
- Set Flutterwave secrets only in Render environment settings.
- Set CREDENTIAL_ENCRYPTION_KEY to URL-safe base64 encoding of 32 random bytes.
- Set CORS_ORIGINS to exact trusted origins.
- Configure email sender and merchant balance reader integrations before enabling those features.
- Confirm health/readiness, webhook URL and provider signature with sandbox transaction.
- Keep live trading disabled until demo soak and independent review pass.
