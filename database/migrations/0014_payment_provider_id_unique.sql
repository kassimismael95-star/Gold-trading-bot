-- A provider transaction can belong to only one internal payment.
CREATE UNIQUE INDEX IF NOT EXISTS ix_payment_provider_id ON payment(provider_id);
