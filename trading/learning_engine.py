
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class TradingLearningEngine:
    """
    Observation-only trading learning engine.

    Records completed trades and management outcomes.
    Produces performance statistics for later evaluation.

    It cannot:
    - Rewrite trading strategy code.
    - Change lot sizing.
    - Increase trading risk.
    - Modify live broker positions.
    - Override the original entry engine.
    """

    def __init__(self, database_path="data/trading_learning.db"):
        self.database_path = str(database_path)
        self.lock = threading.RLock()

        Path(self.database_path).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self._initialise_database()

        self.learning_mode = "OBSERVATION_ONLY"

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=30
        )

        connection.row_factory = sqlite3.Row

        return connection

    def _initialise_database(self):
        with self.lock:
            connection = self._connect()

            try:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS trade_outcomes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_id TEXT NOT NULL,
                        position_id TEXT NOT NULL,
                        symbol TEXT,
                        direction TEXT,
                        entry_price REAL,
                        exit_price REAL,
                        volume REAL,
                        realised_profit REAL,
                        entry_confidence REAL,
                        momentum_state TEXT,
                        reversal_state TEXT,
                        exit_reason TEXT,
                        market_context TEXT,
                        opened_at TEXT,
                        closed_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(account_id, position_id)
                    )
                """)

                connection.execute("""
                    CREATE TABLE IF NOT EXISTS management_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_id TEXT NOT NULL,
                        position_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        event_reason TEXT,
                        previous_stop_loss REAL,
                        new_stop_loss REAL,
                        previous_take_profit REAL,
                        new_take_profit REAL,
                        volume_before REAL,
                        volume_after REAL,
                        realised_profit REAL,
                        market_context TEXT,
                        created_at TEXT NOT NULL
                    )
                """)

                connection.execute("""
                    CREATE TABLE IF NOT EXISTS learning_observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_id TEXT NOT NULL,
                        observation_type TEXT NOT NULL,
                        observation TEXT NOT NULL,
                        sample_size INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                connection.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trade_account
                    ON trade_outcomes(account_id)
                """)

                connection.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trade_symbol
                    ON trade_outcomes(symbol)
                """)

                connection.execute("""
                    CREATE INDEX IF NOT EXISTS idx_events_position
                    ON management_events(position_id)
                """)

                connection.commit()

            finally:
                connection.close()

    @staticmethod
    def _json(value):
        return json.dumps(
            value if value is not None else {},
            default=str,
            separators=(",", ":")
        )

    def record_trade_outcome(
        self,
        account_id,
        position_id,
        symbol,
        direction,
        entry_price,
        exit_price,
        volume,
        realised_profit,
        entry_confidence=None,
        momentum_state=None,
        reversal_state=None,
        exit_reason=None,
        market_context=None,
        opened_at=None,
        closed_at=None
    ):
        """
        Store a completed position outcome.

        Repeated reports for the same account and position update
        the existing record instead of duplicating it.
        """
        account_id = str(account_id)
        position_id = str(position_id)

        if not account_id or not position_id:
            raise ValueError("Account ID and position ID are required")

        closed_at = closed_at or utc_now()

        values = (
            account_id,
            position_id,
            str(symbol),
            str(direction),
            float(entry_price),
            float(exit_price),
            float(volume),
            float(realised_profit),
            entry_confidence,
            momentum_state,
            reversal_state,
            exit_reason,
            self._json(market_context),
            opened_at,
            closed_at,
            utc_now()
        )

        with self.lock:
            connection = self._connect()

            try:
                connection.execute("""
                    INSERT INTO trade_outcomes (
                        account_id,
                        position_id,
                        symbol,
                        direction,
                        entry_price,
                        exit_price,
                        volume,
                        realised_profit,
                        entry_confidence,
                        momentum_state,
                        reversal_state,
                        exit_reason,
                        market_context,
                        opened_at,
                        closed_at,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                    ON CONFLICT(account_id, position_id)
                    DO UPDATE SET
                        exit_price = excluded.exit_price,
                        realised_profit = excluded.realised_profit,
                        momentum_state = excluded.momentum_state,
                        reversal_state = excluded.reversal_state,
                        exit_reason = excluded.exit_reason,
                        market_context = excluded.market_context,
                        closed_at = excluded.closed_at
                """, values)

                connection.commit()

            finally:
                connection.close()

        return {
            "recorded": True,
            "account_id": account_id,
            "position_id": position_id
        }

    def record_management_event(
        self,
        account_id,
        position_id,
        event_type,
        event_reason=None,
        previous_stop_loss=None,
        new_stop_loss=None,
        previous_take_profit=None,
        new_take_profit=None,
        volume_before=None,
        volume_after=None,
        realised_profit=None,
        market_context=None
    ):
        """
        Record an actual or broker-confirmed management event.
        """
        with self.lock:
            connection = self._connect()

            try:
                cursor = connection.execute("""
                    INSERT INTO management_events (
                        account_id,
                        position_id,
                        event_type,
                        event_reason,
                        previous_stop_loss,
                        new_stop_loss,
                        previous_take_profit,
                        new_take_profit,
                        volume_before,
                        volume_after,
                        realised_profit,
                        market_context,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(account_id),
                    str(position_id),
                    str(event_type),
                    event_reason,
                    previous_stop_loss,
                    new_stop_loss,
                    previous_take_profit,
                    new_take_profit,
                    volume_before,
                    volume_after,
                    realised_profit,
                    self._json(market_context),
                    utc_now()
                ))

                connection.commit()

                event_id = cursor.lastrowid

            finally:
                connection.close()

        return {
            "recorded": True,
            "event_id": event_id
        }

    def get_account_performance(self, account_id):
        """
        Calculate realised trading performance for one account.
        """
        with self.lock:
            connection = self._connect()

            try:
                rows = connection.execute("""
                    SELECT
                        COUNT(*) AS total_trades,
                        SUM(CASE
                            WHEN realised_profit > 0 THEN 1
                            ELSE 0
                        END) AS winning_trades,
                        SUM(CASE
                            WHEN realised_profit < 0 THEN 1
                            ELSE 0
                        END) AS losing_trades,
                        SUM(realised_profit) AS total_realised_profit,
                        AVG(realised_profit) AS average_profit,
                        MAX(realised_profit) AS best_trade,
                        MIN(realised_profit) AS worst_trade
                    FROM trade_outcomes
                    WHERE account_id = ?
                """, (str(account_id),)).fetchone()

            finally:
                connection.close()

        total = rows["total_trades"] or 0
        wins = rows["winning_trades"] or 0
        losses = rows["losing_trades"] or 0

        return {
            "account_id": str(account_id),
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": (
                wins / total
                if total else None
            ),
            "total_realised_profit": (
                rows["total_realised_profit"] or 0.0
            ),
            "average_profit": rows["average_profit"],
            "best_trade": rows["best_trade"],
            "worst_trade": rows["worst_trade"],
            "learning_mode": self.learning_mode
        }

    def get_symbol_performance(self, account_id):
        """
        Compare realised outcomes by traded symbol.
        """
        with self.lock:
            connection = self._connect()

            try:
                rows = connection.execute("""
                    SELECT
                        symbol,
                        COUNT(*) AS total_trades,
                        SUM(CASE
                            WHEN realised_profit > 0 THEN 1
                            ELSE 0
                        END) AS winning_trades,
                        SUM(realised_profit) AS total_profit,
                        AVG(realised_profit) AS average_profit
                    FROM trade_outcomes
                    WHERE account_id = ?
                    GROUP BY symbol
                    ORDER BY total_profit DESC
                """, (str(account_id),)).fetchall()

            finally:
                connection.close()

        return [
            {
                "symbol": row["symbol"],
                "total_trades": row["total_trades"],
                "winning_trades": row["winning_trades"],
                "total_profit": row["total_profit"] or 0.0,
                "average_profit": row["average_profit"]
            }
            for row in rows
        ]

    def create_learning_observation(
        self,
        account_id,
        observation_type,
        observation,
        sample_size
    ):
        """
        Save a learning observation for review.

        An observation is not an approved trading-rule change.
        """
        with self.lock:
            connection = self._connect()

            try:
                cursor = connection.execute("""
                    INSERT INTO learning_observations (
                        account_id,
                        observation_type,
                        observation,
                        sample_size,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    str(account_id),
                    str(observation_type),
                    self._json(observation),
                    int(sample_size),
                    utc_now()
                ))

                connection.commit()

                observation_id = cursor.lastrowid

            finally:
                connection.close()

        return {
            "recorded": True,
            "observation_id": observation_id,
            "mode": self.learning_mode
        }

    def get_learning_observations(self, account_id):
        with self.lock:
            connection = self._connect()

            try:
                rows = connection.execute("""
                    SELECT *
                    FROM learning_observations
                    WHERE account_id = ?
                    ORDER BY id DESC
                """, (str(account_id),)).fetchall()

            finally:
                connection.close()

        results = []

        for row in rows:
            item = dict(row)

            try:
                item["observation"] = json.loads(
                    item["observation"]
                )
            except (TypeError, ValueError):
                pass

            results.append(item)

        return results

    def get_recent_trades(self, account_id, limit=100):
        """
        Retrieve recent completed trades for analysis.
        """
        limit = max(1, min(int(limit), 1000))

        with self.lock:
            connection = self._connect()

            try:
                rows = connection.execute("""
                    SELECT *
                    FROM trade_outcomes
                    WHERE account_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                """, (str(account_id), limit)).fetchall()

            finally:
                connection.close()

        results = []

        for row in rows:
            item = dict(row)

            try:
                item["market_context"] = json.loads(
                    item["market_context"]
                )
            except (TypeError, ValueError):
                pass

            results.append(item)

        return results

    def get_status(self):
        return {
            "learning_mode": self.learning_mode,
            "automatic_strategy_changes": False,
            "automatic_risk_increases": False,
            "database": self.database_path
        }
