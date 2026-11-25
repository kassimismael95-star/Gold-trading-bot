"""Run from a managed scheduler/cron process; never start duplicate schedulers per web worker."""
def run_balance_sync(app):
    with app.app_context():
        from .wallet_balance_sync import sync_all_provider_balances
        return sync_all_provider_balances()


def start_periodic_balance_sync(app, interval_seconds=3600):
    """Start a best-effort periodic sync loop protected by a PostgreSQL advisory lock.

    Each web worker may start a thread, but only one process acquires the lock at
    a time. The loop is opt-in and should be enabled only when the host keeps the
    service running; sleeping/free web instances cannot guarantee hourly checks.
    """
    import os, threading, time
    if app.extensions.get("balance_sync_thread_started"):
        return
    app.extensions["balance_sync_thread_started"] = True
    interval=max(300,int(interval_seconds))

    def loop():
        from sqlalchemy import text
        while True:
            try:
                with app.app_context():
                    from ..extensions import db
                    engine=db.engine
                    with engine.connect() as connection:
                        acquired=False
                        try:
                            acquired=bool(connection.execute(text("SELECT pg_try_advisory_lock(884201761) ")).scalar())
                            if acquired:
                                from .wallet_balance_sync import sync_all_provider_balances
                                try:
                                    sync_all_provider_balances()
                                except Exception:
                                    db.session.rollback()
                                    app.logger.exception("merchant balance sync failed")
                                try:
                                    cleanup_operational_tables()
                                except Exception:
                                    db.session.rollback()
                                    app.logger.exception("operational cleanup failed")
                        finally:
                            if acquired:
                                connection.execute(text("SELECT pg_advisory_unlock(884201761)"))
                                connection.commit()
            except Exception:
                app.logger.exception("periodic merchant balance sync failed")
            time.sleep(interval)

    thread=threading.Thread(target=loop,name="gold-balance-sync",daemon=True)
    thread.start()


def cleanup_operational_tables():
    """Bound retention for short-lived security records."""
    from datetime import datetime, timezone, timedelta
    from ..models import RateLimitRecord, TokenBlocklist, EmailChallenge
    from ..extensions import db
    now=datetime.now(timezone.utc)
    RateLimitRecord.query.filter(RateLimitRecord.window_start < now-timedelta(days=7)).delete(synchronize_session=False)
    TokenBlocklist.query.filter(TokenBlocklist.expires_at < now).delete(synchronize_session=False)
    EmailChallenge.query.filter(EmailChallenge.created_at < now-timedelta(days=30)).delete(synchronize_session=False)
    from ..subscriptions.expiry_service import expire_due
    expire_due(now)
    db.session.commit()
