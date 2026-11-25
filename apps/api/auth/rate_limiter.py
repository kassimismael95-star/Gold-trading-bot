"""Database-backed rate limiting for multi-worker deployments.

The key is hashed before persistence so raw email addresses and IPs are not
stored in the limiter table. A process-local fallback is used only outside an
application context (unit-level use).
"""
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from time import time
from sqlalchemy.exc import IntegrityError
from flask import has_app_context, current_app

class RateLimiter:
    def __init__(self, limit=8, window=60):
        self.limit=limit; self.window=window; self.events=defaultdict(deque)

    def allow(self,key):
        if has_app_context():
            try: return self._allow_database(key)
            except Exception:
                # Fail closed in configured production mode; don't silently disable
                # abuse controls if the database is unavailable.
                if current_app.config.get("APP_ENV") == "production":
                    current_app.logger.exception("database rate limiter unavailable")
                    return False
        now=time(); q=self.events[key]
        while q and now-q[0]>self.window: q.popleft()
        if len(q)>=self.limit: return False
        q.append(now); return True

    def _allow_database(self,key):
        from ..extensions import db
        from ..models import RateLimitRecord
        digest=sha256(str(key).encode()).hexdigest()
        now=datetime.now(timezone.utc)
        for attempt in range(2):
            row=RateLimitRecord.query.filter_by(key_hash=digest).with_for_update().first()
            if row is None:
                row=RateLimitRecord(key_hash=digest,count=1,window_start=now,updated_at=now)
                db.session.add(row)
                try: db.session.commit(); return True
                except IntegrityError:
                    db.session.rollback(); continue
            start=row.window_start
            if start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
            if now-start >= timedelta(seconds=self.window):
                row.window_start=now; row.count=1; row.updated_at=now; db.session.commit(); return True
            if row.count >= self.limit:
                db.session.rollback(); return False
            row.count += 1; row.updated_at=now; db.session.commit(); return True
        return False
